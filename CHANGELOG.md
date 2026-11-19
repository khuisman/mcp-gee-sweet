# Changelog

All notable changes to this project are documented in this file.

---

## [Unreleased]

### Breaking change

- **An unset or empty `ENABLED_TOOLS` now loads the `default` tool group, 39 everyday tools across Sheets, Docs, Drive, Calendar and Gmail, instead of every tool.** To keep every tool, set `ENABLED_TOOLS=all` (or `--include-tools all`). `default` leaves out the tools that only work on local files (local upload, download and `sync_folder`, `import_csv_to_sheet`, `create_doc_from_file`, `update_doc_from_file`, `insert_local_images`); add the `local-files` group, e.g. `ENABLED_TOOLS=default,local-files`, to keep them. v0.9.6 announced this change — #1364
- **`copy_sheet` returns `{sheetId, title, index, spreadsheetId}` for the new tab**, where `spreadsheetId` is the spreadsheet it landed in, in place of the raw `copy` and `rename` API responses it returned before. A caller that read `copy` or `rename` needs the new keys. A missing source tab's error now reads `Sheet '<name>' not found` — #1526

### New features

- `ENABLED_TOOLS` and `--include-tools` take tool group names as well as tool names, and register their union: `default`, `all`, one group per service (`sheets`, `drive`, `docs`, `calendar`, `gmail`, `cache`), `local-files` and `comments`. Every group but `all` is under the lowest documented client tool cap (100). An entry that names no tool or group, such as `ALL` or a misspelled name, logs a startup warning instead of being dropped silently. The startup log, the server's instructions to the client, and `server://auth-status` (`tool_selection`) say which tools loaded. `docs/tools.md` lists each tool's groups, and [Tool filtering](https://khuisman.github.io/mcp-gee-sweet/latest/configuration/#tool-filtering) replaces the suggested subsets with the groups. [Client Setup](https://khuisman.github.io/mcp-gee-sweet/latest/client-setup/#choosing-tools-for-your-client) gives the setting for each client — #1364
- `get_sheet_data` takes `value_render`: `formatted` (the default, as before) returns values as the sheet displays them, `unformatted` returns the underlying values (numbers unformatted, dates as serial numbers), and `formula` returns each cell's formula, as `get_sheet_formulas` did. It applies to the values read; with `include_grid_data=True` the grid already carries each cell's formula, value and displayed text — #1526
- `copy_sheet` also copies a tab within its own spreadsheet, as `duplicate_sheet` did: omit `destination_spreadsheet_id` to duplicate in place, right after the source tab unless `insert_index` says otherwise. Copying into another spreadsheet takes `insert_index` too, moving the copy from the end, where Google puts it. A copy into another spreadsheet no longer leaves a stray `Copy of …` tab when its rename or move is refused: a `new_name` the destination already has (ignoring case) is an error before anything is copied, an `insert_index` past the last tab leaves the copy last, and a copy whose rename or move still fails is deleted — #1526

### New tools

- `add_rows_or_columns`, `delete_rows_or_columns`, `resize_rows_or_columns` and `hide_rows_or_columns` add, delete, resize, and hide or unhide rows or columns in a sheet: `dimension` (`rows` or `columns`) picks which, `start` and `end` (inclusive, 0-based) give the range, and `hide_rows_or_columns(hidden=False)` unhides. Each sends the same request as the row-only or column-only tool it replaces — #1525

### Changed

- **`copy_sheet`'s parameters are renamed.** `src_spreadsheet` is now `spreadsheet_id`, `src_sheet` is `sheet`, `dst_spreadsheet` is `destination_spreadsheet_id` and `dst_sheet` is `new_name`; the old names keep working for one release, with a `deprecation_warnings` entry in the result. `new_name` is optional where `dst_sheet` was required, so a call that names neither now makes the copy under Google's own name ("Copy of Sales") instead of failing. A call with neither `destination_spreadsheet_id` nor `dst_spreadsheet` now duplicates the tab in place, and so does one naming the source spreadsheet as its own destination, which used to put the copy last and now puts it right after the source. Its result changes shape too (see **Breaking change**) — #1526
- Renamed and removed tools now get one release of notice. A renamed tool's old name keeps working for one release when it's listed in `ENABLED_TOOLS` or the server runs with `all`, with a startup warning naming the new tool; a tool due for removal says so at the start of its description and warns at startup when `ENABLED_TOOLS` names it; and a renamed parameter's old name keeps working, with a `deprecation_warnings` entry in the result. Each one is listed here under **Deprecated** in the release that deprecates it and under **Removed** in the release after. `server://auth-status` lists deprecated tools under `tool_selection.deprecated_tools`. See the [deprecation policy](https://khuisman.github.io/mcp-gee-sweet/latest/design/#renaming-or-removing-a-tool) — #1209

- `sync_folder`'s over-cap hint names actions the caller can actually take — "Sync a narrower subfolder, a single direction, or set recursive=False." instead of "Narrow folder_id, direction, or recursive scope", where a direction can't be narrowed — and the pagination hint shared by `list_messages`, `list_threads`, `list_doc_comments` and `list_file_activity` now comes from one `pagination_hint` helper, so the hand-copied three can't drift apart. A test collects every hint passed to the size-cap checks in `src/` and pins the full-sentence form #1430 established — #1465

### Deprecated

- The ten row-only and column-only Sheets tools are deprecated and removed in the next feature release. Use `add_rows_or_columns` for `add_rows`/`add_columns`, `delete_rows_or_columns` for `delete_rows`/`delete_columns`, `resize_rows_or_columns` for `resize_rows`/`resize_columns`, and `hide_rows_or_columns` for `hide_rows`/`hide_columns` and, with `hidden=False`, `unhide_rows`/`unhide_columns`, passing `dimension='rows'` or `'columns'`. `start_row`/`start_column` become `start` and `end_row`/`end_column` become `end`; nothing else changes — #1525
- `get_sheet_formulas` is deprecated and removed in the next feature release: use `get_sheet_data` with `value_render='formula'`, which returns `get_sheet_data`'s usual `{spreadsheetId, valueRanges}` dict instead of a bare list. It's no longer in the `default` tool group — #1526
- `duplicate_sheet` is deprecated and removed in the next feature release: use `copy_sheet` with no `destination_spreadsheet_id`, which takes the same `spreadsheet_id`, `sheet`, `new_name` and `insert_index` and returns the same result — #1526
- `copy_sheet`'s `src_spreadsheet`, `src_sheet`, `dst_spreadsheet` and `dst_sheet` parameters are deprecated and removed in the next feature release: use `spreadsheet_id`, `sheet`, `destination_spreadsheet_id` and `new_name` — #1526

### Bug fixes

- A heading holding a character Python's `\w` and github-slugger treat differently slugged wrong: a superscript or fraction digit ("²" in "Area in m²", "½") stayed in the slug where GitHub's own anchor is separator-free (`#area-in-m`), and a combining mark (`cafe\u0301`) was dropped where GitHub keeps it. The GitHub scheme now strips by character category, built from github-slugger's own generation rule, instead of by `\w`. Repeated headings whose suffixed slug collides with a literally-titled one ("Pricelist" twice over plus a real "Pricelist-1") produced two `#pricelist-1` anchors; the suffix now keeps incrementing until the slug is free, as github-slugger does. A `#pricelist` anchor naming headings that differ only by a separator GitHub strips (`Price\xa0List` and `Pricelist`) takes the GitHub reading — a genuine ambiguity between the sites, now documented in docs/design/heading-anchor-resolution.md — #1482
- `get_doc_as_markdown` keeps an emphasis span open across an inline image that shares it, and reads the image's own character style back: a Doc written from `**bold ![logo](x) image**` exported as `**bold** ![](…) **image**` with a plain image in the middle, and a round trip through `update_doc_from_file` wrote the image plain. The read side records the same fields the write side styles on an image (`bold`, `italic`, `underline`, `strikethrough`, highlight, baseline, small caps, code font, alongside the #951 link), and the export renders one span for a run–image–run sequence that shares it — `**bold ![logo](x) image**` — as well as for an image whose own style no run shares (`**![logo](x)**`). A break at an image's boundary, a code run, or a style the image doesn't share keeps the old split rendering, as does a span whose markers would flank an image edge beside a letter or digit (`see**![logo](u)**` keeps literal asterisks under CommonMark), and a line break at a span's outer edge renders outside its link, as a run's edge breaks do. Table cells keep the span too. Styles Markdown has no syntax for (underline, highlight, superscript, small caps) ride on the AST, as a run's do, and stay unwritten, as a run's are — #1509
- `insert_softbreak_paragraph` no longer sends a paragraph-style request unless `named_style_type` is passed: it used to write `NORMAL_TEXT` over the whole paragraph the block landed in by default, so a plain insert wiped the paragraph's existing inline text styles (`updateParagraphStyle(namedStyleType)` re-applies the named style's text properties). The default is now `None` — no `updateParagraphStyle` at all — and passing a named style still writes it over the whole paragraph. Its line-dict vocabulary now lists `font_family`, which was already supported, and the docstring, `style_doc_range`'s Note and the known-limitations entry now state that one range dict carrying `named_style_type` plus text-style fields applies paragraph-style-first in a single call, dropping the wrong second-call workaround — #1489
- A `<pre>` inside a table cell is styled as code, as a `<pre>` at the body level is: its text keeps the line breaks #1215 gave it and now reads in Courier New, where it used to keep the breaks but look like plain text in the cell. Text after the `</pre>` in the same cell stays plain — #1417
- An `<li>` that is the first item of a `<ul>` and holds only a styled block (a `<p data-style="title">` or `<p data-style="subtitle">`, HTML input, with no `&nbsp;` before it) is that block, indented under the list with no bullet, as in v0.9.5, instead of an empty bullet above it: a browser draws the item's marker beside the block's first line, so the item reads as one line (#1075's premise put the marker on a line of its own). Every other item keeps the bullet #1075 gives it — one with text of its own, a later item of the list, an item of an `<ol>` (whose `start`/`value` numbering counts it), or one whose only content is a nested list, quote, code block or rule. Applies to `create_doc`, `write_doc_content`, `create_doc_from_file` and `update_doc_from_file` — #1414
- An image after a styled run no longer takes that run's character styles, and neither does the alt text that replaces an unfetchable image: Docs passes the character before an insert's styles on to what's inserted, so a badge after a superscript note came out raised and shrunk, and a fallback after bold or highlight text came out bold or highlighted. Every embedded image now goes out with a style request that clears the inherited emphasis, position, small-caps and highlight fields — bold, italic, underline, strikethrough, baselineOffset, smallCaps and backgroundColor — keeping only the image's own link (#977); an image's fallback text gets the same clearing over its whole range, carrying its link as before (#1099). Size and color still pass through, so a fallback reads like the text around it. Applies to every tool that writes Markdown or HTML, table cells included — #1334
- An image keeps the character style of the span it sits in, and so does the alt text that replaces an unfetchable one: `**Build: ![status](badge.svg) passing**` writes a bold "status" where it used to be plain in the middle of the bold run, and the same holds for italic, underline, strikethrough, `<mark>` highlight, `<sup>`/`<sub>` and inline code. Alt text written right after an inline code span no longer comes out in Courier New: ``Run `make` ![build](badge.svg)`` used to read back as `` `make build` ``. A list item whose whole text is a styled image keeps a plain bullet. Applies to every tool that writes Markdown or HTML, table cells included — #1475
- A linked image's alt text, written when Docs can't fetch the image, is underlined like any other link again: it had the link color but no underline, because the request that cleared the styles it inherited also cleared the underline Docs gives a link. An unlinked fallback still drops an underline from the text before it — #1504
- HTML input: in a table cell, the text after a nested table starts on the line that follows that block, so the source spacing between `</table>` and the text collapses: `<td>Before <table>…</table> After</td>` shows `After` flush with the cell's text, where the space used to indent it by one character. A nested table that builds no node into the cell (an empty `<table></table>`) collapses nothing. An authored `&nbsp;` there stays, and a cell's own leading spacing is untouched. Applies to `create_doc`, `write_doc_content`, `create_doc_from_file`, `update_doc_from_file` and `upload_file`'s Markdown Doc — #1418

## [0.9.6] — 2026-11-11

### Upcoming change

- **An upcoming release loads a smaller default tool set when `ENABLED_TOOLS` is unset.** To keep every tool, set `ENABLED_TOOLS=all`. Until then, a server started with `ENABLED_TOOLS` unset or empty logs this as a warning at startup — #1363

### New tools

- Gmail drafts can now be reviewed, edited, and discarded before sending: `list_drafts` (query and pagination; each draft's recipients, subject, and snippet), `get_draft` (same shape as `get_message`), `update_draft` (replaces the content and keeps the draft ID, the thread of a reply draft, and its send-as From; `keep_attachments=True` keeps the existing attachments), and `delete_draft`. None of them sends mail; `send_draft` is still the only way a draft goes out — #1205

### New features

- Each GitHub Release now carries an MCP Bundle, `mcp-gee-sweet-<version>.mcpb`, which installs the server in Claude Desktop in one click: the install dialog asks for the OAuth client file, and nothing goes into `claude_desktop_config.json` by hand. The bundle uses OAuth only and keeps its token at `~/.mcp-gee-sweet-token.json`. See [Install as a bundle](docs/client-setup.md#install-as-a-bundle) — #1036
- `ENABLED_TOOLS=all` and `--include-tools all` register every tool, the same as leaving them unset. `all` used to be read as a tool name, so the server started with no tools and no error — #1363

### Changed

- **Behavior change: Gmail no longer sends on the agent's call alone.** With the new default `GMAIL_SEND=confirm`, `send_message` and `reply_to_message` save the email as a draft (a reply in its thread) and send it only after the user confirms it in a form the MCP client shows; `send_draft` asks the same way. Declining, cancelling, no answer, or a client that can't show the form leaves the draft unsent and returns `sent: false` with its `draft_id`. Confirmation needs a client on the 2025-11-25 handshake with form elicitation; on 2026-07-28 connections mail stays a draft. The confirmation and the result flag recipients outside a Workspace organization, more than `GMAIL_SEND_WARN_RECIPIENTS` (default 10) recipients, and any Bcc. A client hook that auto-accepts elicitations makes this the same as `direct`. Set `GMAIL_SEND=direct` for the old immediate delivery. Every send result now has a `sent` field — #1081
- **Claude Code users: sends are held as drafts.** Claude Code currently connects on MCP 2026-07-28, where the server can't ask for confirmation, so under the new default every `send_message` and `reply_to_message` from Claude Code returns `sent: false` with the email saved in Gmail's Drafts folder, and `send_draft` refuses. Send from Drafts, or set `GMAIL_SEND=direct` to keep sending at once. Confirmation on 2026-07-28 connections is tracked in #1235 — #1081
- Markdown input (`create_doc`/`write_doc_content` with `content_format='markdown'`, `create_doc_from_file`, `update_doc_from_file`) is now parsed as CommonMark plus GitHub-flavored Markdown (markdown-it-py), the dialect models and most tools write, instead of Python-Markdown. Markdown that renders differently — #1116:
  - A list, task list, quote, table or code block written directly under a paragraph, list item or quote line, with no blank line, now starts its own block instead of being joined to the text above. A pipe table under a list item or quote line also starts its own block (plan rule D2).
  - Sub-lists nest at 2 or 3 spaces of indent, under bullets and numbered items alike, and numbering continues after them (plan rule D1) — #1071.
  - A paragraph, code block or quote indented under a list item belongs to that item. A fenced code block inside a list item renders as code instead of literal text.
  - `~~text~~` is struck through. `1)` starts a numbered list. `\` at the end of a line is a line break. A backslash before any ASCII punctuation character escapes it.
  - `www.example.com` and `me@example.com` are linked, like bare `https://` URLs already were (`autolink_urls=False` turns all three off); a `www.` link points to `https://` (#1281). `README.md`, `file.py` and `ftp://` URLs are not. A bare URL is now linked only where GitHub links one: at the start of a line or after a space, `*`, `_`, `~` or `(`. So `URL:https://example.com`, `<b>https://example.com</b>` and a URL right after a code span or link stay plain text, where they used to be linked; put a space before the URL, or write `<https://example.com>`.
  - Bold inside italic (`*a **b** c*`) keeps both styles. `#hashtag` and `####### seven` stay paragraphs instead of becoming headings.
  - A link or image whose path contains spaces (`![shot](./Screen Shot.png)`, `[notes](./My Notes.md "Notes")`) still works, as it did before, although CommonMark itself would leave it as text.
  - Two quotes separated by a blank line render as two quotes.
  - A line of only `-` is an empty list item (an empty bullet, #1075, under Bug fixes) instead of a setext heading underline or literal text. Right under a paragraph's text it's still a heading underline, as in CommonMark and on GitHub: put a blank line before it to get an empty item.
  - YAML front matter (`---` … `---` at the top) now renders as a rule and then a Heading 2 of its text, where it used to render as a rule, a paragraph and a rule. It's still shown either way (#1173).
  - A list with a blank line between items, or with a paragraph or code block indented under an item, stays one list with every bullet and number, where Python-Markdown dropped some of those items out of the list (#1111, fixed by #1164). The numbering continues past a block inside a numbered item too (#1094, under Bug fixes).
  - A line of `---` (or `===`) right under a list item's text makes that text a heading inside the item, as CommonMark reads a setext underline: `- a` then `  ---` is a bulleted Heading 2 "a" (#1094), not an item followed by a rule. Write the rule as `***` to keep the item and the rule.
- **Behavior change: `upload_file(source_format='markdown', convert_to_doc=True)` writes the Doc with the same converter as `create_doc(content_format='markdown')`**, instead of converting with Python-Markdown and handing the HTML to Drive's import. Nested lists keep their levels, code blocks and inline code are monospace every time (Drive's import picked the font differently from run to run), task items get checkboxes, and bare URLs are linked. Images resolve as in `create_doc`: a local path or `drive:<file_id>` is uploaded or shared temporarily, and the result carries per-image outcomes under `images`, and `dropped_links` as `create_doc` reports them. If writing the content fails after the Doc was created, the result is `{"error", "fileId"}` plus those fields. Without `convert_to_doc`, a Markdown upload's HTML file now comes from the same converter too. `source_format='html'` still uses Drive's HTML import. Python-Markdown `extra` syntax that this converter doesn't read is no longer rendered on either path. A footnote written as prose stays literal text, marker and note line both; a one-word or URL note (`[^1]: note`) reads as a link reference definition, so the note line disappears and the marker shows as `^1`. These also stay literal text: definition lists (`Term` / `: definition`), abbreviations (`*[HTML]: ...`), `{#id}` / `{.class}` attribute lists, and Markdown inside an HTML block marked `markdown="1"` (see `docs/known-limitations.md`). `upload_file` also gains `auto_downscale`, as `create_doc` has, for an oversized image in a Markdown Doc — #1102

### Bug fixes

- A block container inside an open paragraph, list item or heading (`<p>x<div>y</div>z</p>`, `<li>a<div>b</div>c</li>`) breaks the block's text onto its own line, as a browser draws it, instead of running into the block's text on one line: the Doc read `xyz`. **Behavior change for HTML input:** a container holding the block's only text still keeps the block whole (`<li><div>x</div></li>` is one bullet, `<h1><div>x</div></h1>` one heading), an empty container draws no line of its own, a `<br>` right at the boundary is the boundary's break rather than an extra blank line, and a container in a `<pre>` or a table cell keeps its old treatment. Applies to `create_doc`, `write_doc_content`, `create_doc_from_file`, `update_doc_from_file` and `upload_file`'s Markdown Doc — #1403
- A table's `<caption>` is no longer silently dropped with all other table-scope text: it reads as a paragraph above the table, keeping its inline styles, its leading/trailing formatting whitespace collapsed, and — inside a cell — its place ahead of a nested table, on the line after any text the cell already holds. A caption left open closes at the first row as a browser's parser does, closing the inline tags opened inside it, so an unclosed `<b>`, `<code>` or `<a href>` no longer leaks its style into the table's cells or past the table; the implied close fires only for the caption's own table, so a table nested inside a caption no longer has its first row close that caption, which popped the nested table along with it and made the nested row the outer table's own, losing the outer table's next row. A caption that wraps across source lines is one paragraph (its line breaks are soft breaks), a `<br>` that ends it draws no empty line, and a table with no rows still keeps its caption — #1402
- A `#pricelist` link to a heading written ``Price&nbsp;List`` — a non-breaking space, as HTML input with `&nbsp;` produces — or ``Price\tList`` resolved to nothing: the GitHub-scheme slugger hyphenated every whitespace run, where GitHub's real anchor (github-slugger) strips a tab, an NBSP and a heading's `<br>` break with no hyphen. Only a literal space becomes a hyphen now, and the same strip makes a `<br>` heading's exported slug separator-free, as GitHub's own is — #1460
- Two paragraphs separated by a blank line show a gap in a Doc instead of reading as one paragraph with a line break: 10pt below the first, in a quote and a list item too, on every tool that writes Markdown or HTML with this server's converter. A Doc whose NORMAL_TEXT has spacing keeps it, and `apply_theme` with a NORMAL_TEXT `space_above` or `space_below` replaces the gap. `get_doc_theme` no longer reports this gap, or the spacing or font of a quote, rule or code block, as the Doc's NORMAL_TEXT, unless the Doc has no body text, and then only the font. It also no longer reads one run's inline bold or code span as the Doc's style, and a style whose first paragraph has no explicit style reports nothing — #1382
- A list shows the same 10pt gap from the paragraphs around it: below an intro line such as `Install the headers:` and below the list's last item, a nested one or a paragraph inside it included, as Drive's import leaves an empty line on both sides. A paragraph inside an item and a sublist after it get the gap too. Items of one list keep their list spacing, a heading item or a code block at the list's edge keeps its own spacing, and a list inside a quote gets no gap, since the quote bar wouldn't cover it. A Doc whose NORMAL_TEXT has spacing keeps it, and `apply_theme` replaces this gap as it does the one between paragraphs — #1389
- `--include-tools=a,b`, written with `=`, filters the tools like `--include-tools a,b`. It used to be ignored, so the server registered every tool, and `mcp-gee-sweet auth` asked for every scope. `auth` also refuses an abbreviated option now, such as `--include` — #1363
- A list item with no text (a line of only `-` or `2.`, or an `<li></li>`) is an empty bullet instead of being dropped, so the list keeps every item and a numbered list every number. A list nested under an empty item is one level deeper, as is a code block, quote or horizontal rule that is the item's only content (a rule there used to be dropped). **Behavior change for HTML input:** an `<li>` that holds only whitespace or `&nbsp;`, or that wraps only a nested list (`<li><ul>…</ul></li>`), is now an empty bullet with the nested list one level under it, where it used to produce nothing. Applies to `create_doc`, `write_doc_content`, `create_doc_from_file`, `update_doc_from_file` and `upload_file`'s Markdown Doc — #1075
- A numbered list keeps its numbering after a bulleted list nested in one of its items (`1. A`, `   - a`, `2. B` shows 2, not 1), at every level; a sublist nested in one of the other type used to split the outer list into separate lists. A sublist that follows another sublist of a different type under the same item starts its own numbering. Applies to `create_doc`, `write_doc_content`, `create_doc_from_file` and `update_doc_from_file` — #1072
- Two lists of the same type written one after the other, with a different marker (`-` then `*`, or `1.` then `1)`), render as two lists instead of one: the second numbered list starts again at 1, at the top level and as a second sublist under one item (`1. P`, `    1. a`, `    1) b` shows b as a., not b.). A numbered sublist that follows a deeper numbered list (`1. A`, `   - b`, `     1. c`, `   1. d`) no longer joins it. Applies to `create_doc`, `write_doc_content`, `create_doc_from_file`, `update_doc_from_file` and `upload_file`'s Markdown Doc — #1241
- A block inside a list item (a second paragraph, a code block, a quote, a heading, a table, a rule or an image indented under the item) stays inside it: it's indented to the item's text, with no bullet of its own, and the list continues past it, so `1. Clone:`, a code block, `2. Install.` shows 2, not 1. A quote inside an item is indented one step past the item's text, with its border. An item whose text is a heading (`- # Title`) is a bulleted heading instead of an unlisted heading. **Behavior change for HTML input:** text after a nested list, quote, code block, paragraph or rule inside an `<li>` is a paragraph indented under that item, where it used to become a new bullet (or the next number) of its own. Applies to `create_doc`, `write_doc_content`, `create_doc_from_file`, `update_doc_from_file` and `upload_file`'s Markdown Doc. `get_doc_as_markdown` still exports such a block at the margin and a bulleted heading as a plain item (#1302) — #1094

---

## [0.9.5] — 2026-10-24

Security hotfix on top of v0.9.4. No new tools.

### Security

- Requires `certifi>=2026.10.19`. Older certifi bundles still trust the eight eMudhra/emSign intermediate CAs, whose weak EC keys let a TLS chain through them be forged ([PSF notice](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576)). certifi backs the TLS connection on every Google API call. v0.9.4's lock pinned certifi `2026.5.20`, and no earlier version set a minimum, so `pip install -U mcp-gee-sweet` kept whatever certifi an environment already had — #1217

**What you need to do yourself.** A library can't upgrade your tooling for you:

- Upgrade pip to 26.2.2 or later, and uv to 0.13.4 or later. Both shipped fixes for the same incident.
- Rebuild any Docker image without the cache (`docker build --no-cache ...`), so a cached layer doesn't keep the old certifi.

---

## [0.8.1] — 2026-07-05

Defects and documentation cleanup. No new tools.

### Bug fixes

- `get_sheet_data`: `include_grid_data=True` without a range now auto-detects the actual used range and enforces a response-size safety cap, instead of fetching/returning the sheet's full padded grid — #235
- Response-size safety net generalized to `export_file`, `get_doc_content`, `get_multiple_sheet_data`, `find_in_spreadsheet`, and `list_file_activity` — #242
- `create_doc_from_file`: `\$` markdown escape now renders as a literal `$` instead of passing through untouched — #213
- Unrecognized tool keyword arguments now raise a validation error instead of being silently dropped — #239
- Cache: graceful recovery from read-only or corrupted DB files instead of failing to start — #212
- `get_multiple_spreadsheet_summary`: `rows_to_fetch=0` now consistently returns no data rows regardless of prior cache state (previously returned different results on a cold vs. warm cache) — #254
- `write_doc_content`: fixed a bug where an explicit font size/family override left on a document's trailing paragraph mark by prior content (e.g. a table or fenced code block) could leak into newly-written plain-paragraph content — #255

### Documentation

- `docs/tools.md` and the tool-filtering section of `docs/configuration.md` are now regenerated from tool docstrings via a pre-commit hook (`scripts/gen_tool_docs.py`) — #94
- `CONTRIBUTING.md` rewritten for the full contributor experience: PR scope rules, best-effort review turnaround, Code of Conduct, and the current label table — #95, #237
- Fixed tool-count drift, known-limitations entries, and auth-method ordering across the docs; removed stale `TODO.md` — #236
- Release gate scoping policy: a stable release can substitute Smoke + targeted Domain QA runs for Full Regression when a source-diff audit shows the change is narrow — see `docs/decisions/decision-testing.md`

### QA

- Scoped release gate: 148 PASS / 2 FAIL / 16 SKIP across 166 test cases. Both FAILs were real bugs found during this pass (`rows_to_fetch=0` cache-clamp inconsistency, `write_doc_content` font contamination) — fixed and re-verified live before release, not deferred. See `docs/qa/runs/v0.8.1.md`.

---

## [0.8.0] — 2026-06-29

### New tools

**Google Sheets**
- `delete_sheet` — remove a sheet tab from a spreadsheet
- `delete_rows` / `delete_columns` — remove rows or columns by index
- `clear_values` — erase cell values while preserving formatting
- `format_cells` — apply number formats, alignment, and text styles
- `merge_cells` / `unmerge_cells` — merge or split cell ranges
- `freeze` — freeze rows and/or columns
- `sort_range` — sort a range by one or more columns

**Google Drive**
- `list_shared_with_me` — list files shared with the authenticated user
- `list_recent_files` — list recently modified files, optionally filtered by type and recency window
- `get_storage_quota` — return Drive storage usage and limit
- `list_file_activity` — fetch file activity history via the Drive Activity API v2

**Google Docs**
- `insert_inline_image` — insert an image into a document at a specified location
- `insert_table_row` / `delete_table_row` — add or remove rows in a Docs table
- `insert_table_column` / `delete_table_column` — add or remove columns in a Docs table
- `create_header` / `create_footer` — add a header or footer section to a document

**Google Calendar**
- RRULE recurrence rules for `create_event` and `update_event` — supports weekly, daily, monthly, and custom patterns
- `expand_recurring` parameter on `list_events` — expand recurring events into individual instances (default) or return the master event

### New features

- `.env` file support — `src/mcp_gee_sweet/.env` is loaded at startup; template at `.env.template`
- Structured access logging — `DEBUG_LEVEL`, `LOG_FILE`, and `ACCESS_LOG_FILE` env vars write per-request timing logs in `"IP" "UA" "TOOL name" status elapsed` format

### Bug fixes

- `list_folders`: trashed folders now excluded from results (`trashed=false` filter added to Drive query) — #216
- `get_file_metadata`: `size` field suppressed for Google Workspace files (Docs, Sheets, Slides etc.) which do not consume storage quota — #217
- `list_events`: `time_min` now defaults to the current UTC time when omitted, so only upcoming events are returned by default — #218
- Docs: blank paragraph before a table no longer adds extra height — #190
- Docs: inherited heading `fontSize` cleared when filling table cells to prevent style bleed — #189
- Docs: `headerId` / `footerId` retrieval made robust against missing segment metadata — #145–#147
- Security: bumped `pydantic-settings` to 2.7.1+ (CVE symlink traversal fix)

### Infrastructure

- MCP SDK floor pin raised to `>=1.27.0`
- GitHub security scaffolding: `SECURITY.md`, `CONTRIBUTING.md`, branch protection, Dependabot
- `known-limitations.md` added to docs
- Full QA regression suite (383 PASS / 8 FAIL / 44 SKIP on 2026-06-28; all 8 failures resolved or filed)

---

## [0.7.0] — 2026-06-02

Initial stable release. See README for the full tool list.
