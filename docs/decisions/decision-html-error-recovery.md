# Decision: How `html_to_ast` Recovers From Malformed HTML

**Date:** 2026-11-01
**Status:** decided. Option A (maintainer, 2026-11-01), with justhtml as the library
(maintainer, 2026-11-27; see [Library choice](#library-choice-2026-11-27)).
**Tracking:** #1329 (the bundled defects below)
**Snapshot commit:** `develop` at `730b7dc7`; PR #1316 at `589d3991`

## Background

`tools/docs/html_parser.py` turns HTML into the Docs AST. It subclasses the standard
library's `html.parser.HTMLParser`, which is a *tokenizer*: it reports start tags, end tags
and text, in order, and nothing else. It builds no tree and does no error recovery. What a
browser does with `<p><b>x</p>`, a stray `</b>`, `<sup>a<sub>b</sup>c</sub>`, or a cell with no
`</td>` is the HTML Standard's *tree construction* stage (§13.2.6: the stack of open elements,
the list of active formatting elements, the adoption agency algorithm, implied end tags).
`html_to_ast` does that job itself, by hand, in event handlers.

Malformed HTML reaches the parser two ways only. Markdown never produces it: markdown-it
writes well-formed HTML for everything it parses. It arrives through raw HTML a user writes
inside Markdown (markdown-it's `html=True` passes it through) and through
`content_format="html"`.

### What PR #1316 showed

#1231 asked for `<del>`, `<sub>`/`<sup>` and `<mark>` to map onto `Run` fields the emitter
already writes. Round 0 (`f8a25f82`) was +91 lines in `html_parser.py`, and every TC-MD503
case rendered correctly live. QA's code review then found parser-state edge cases with
unbalanced tags, and the fix for those became a rewrite of how inline styling is tracked.
Six QA rounds followed:

| Round | `html_parser.py` change | QA result |
|---|---|---|
| 0 | +91 / −2 | 8 findings: new tags' scope across cells, items and tables; one regression |
| 1 | +199 / −149, one inline-tag stack | all fixed; 2 new regressions, 7 more findings |
| 2 | +115 / −91, reopen queue, links on the stack | all fixed; 3 new regressions (one content loss) |
| 3 | +80 / −36, cross-scope close fallback | all fixed; 2 new regressions (one quadratic), 4 older defects |
| 4 | +186 / −96, constant-time stack | all fixed; 3 paths still quadratic |
| 5 | +142 / −76, indexed stack | all fixed; 3 new regressions (quadratic, `<th>` bold, content loss) |

The PR stood at +1,093 / −180 overall. Each round fixed every named finding and introduced
new ones in the same mechanism. The pieces it added are pieces of the Standard's algorithm
under other names: scope markers, a list of active formatting elements reopened in the
next block, a cap of 3 identical reopened entries (the Standard's "Noah's Ark" clause), an
`<a>` that closes an open `<a>`. Rebuilding that algorithm piece by piece, driven by
adversarial review inputs, has no natural end point.

## The defects on `develop` today

These are reproduced with `html_to_ast` on `develop` (static, unit-level; no Docs API call).
The "browser" column is the tree html5lib and lexbor build.

| Input | `develop` | Browser | Kind |
|---|---|---|---|
| `<table><tr><td>a<td>b</table><p>after</p>` | table lost, only "after" | 2-cell table | content loss |
| `<table><tr><td>a</td><tr><td>b</td></table>…` | table lost | 2-row table | content loss |
| `<p>a</p></table><p>b</p>c` | only "a" | "a", "b", "c" | content loss |
| `<p><b>a</p>bare` | "bare" dropped | "bare" kept | content loss |
| `<p><s>a</p></s><p>b</p>` | "b" struck | "b" plain | styling |
| `<table><tr><td><s>a</td><td>b</td>…` | "b" struck | "b" plain | styling |
| `<p><b>a</p><table><tr><td>x</td>…` | "x" bold | "x" plain | styling |
| `<b><p>x</b></p>` | "x" plain | "x" bold | styling |

Two behaviors that look like leaks match a browser and aren't defects:
`<p><s>a</p><p>b</p>` strikes "b", and `<p><a href="1">x</p><p>y</p>` links "y". The
Standard reopens an unclosed formatting element in the next block.

PR #1316's QA rounds list more inputs of the styling kind (misnested `<sup>`/`<sub>`, a
list item's own `<p>`, formatting carried past a list depending on whether `</p>` came
first). Most become reachable only once `<sub>`/`<sup>`/`<mark>` exist, and they are the
same class.

## Options

### Option A: build the tree with an HTML5 parser, then walk it

Parse with a library that implements the Standard's tree construction, then walk the
finished tree to the AST. A text node's inline styles are the inline elements above it;
its block is the nearest block ancestor. Every row in the table above comes out as the
browser column, with no project code for recovery.

Candidate libraries, checked 2026-11-01:

| Library | Kind | Latest release | Adversarial input, n = 8,000 (24,000 tags) | 427 KB document |
|---|---|---|---|---|
| selectolax (lexbor backend) | C extension, binary wheels | 1.0.2, 2026-10-22 | 0.005 s | 0.016 s |
| justhtml | pure Python, no runtime deps | 3.16.0, 2026-10-26 | 0.19 s | 0.20 s |
| html5lib | pure Python, `six` + `webencodings` | 1.1, 2020-06-22 | 2.1 s (superlinear) | 0.66 s |

The adversarial input is QA round 6's `'<p>' + '<b>'*n + '<i>'*n + '</b>'*n + 'x</p>'`
(3n tags). The 427 KB document is 5,000 repetitions of
`<p>para <b>bold</b> <a href='uN'>link</a> <sup>2</sup></p><ul><li>item N</li></ul>`,
well-formed. Each time is one parse in a scratch environment.

html5lib is the reference implementation but unmaintained and superlinear on adversarial
input. selectolax is the fast, maintained choice; it adds a compiled dependency (precedent:
Pillow, `decision-pillow-image-dependency.md`). justhtml avoids a compiled dependency but is
young.

**Pros:** correct by construction; deletes most of the hand-written state. Many of
`html_parser.py`'s invariants in `CLAUDE.md` exist only because the parser sees tags one at
a time (resumed segments, `_block_stack` frames, stale frames matched by list ids, the
inline-tag-depth bare-text rule) and become plain tree structure.
**Cons:** a rewrite of a ~1,400-line module with a long incident history. Output on
malformed input changes to the browser's, so tests that pin `develop`'s behavior change.
Some current rules are deliberate departures that a walker has to keep, for example
#994's href-less `<a name>` inside a link. A new runtime dependency.

### Option B: a planned, hand-written recovery model

Decide which recovery rules this parser supports, write them down, and implement them as a
design rather than finding by finding.

**Pros:** no dependency; the rule set can be smaller than a browser's.
**Cons:** a model good enough to stop the review findings converges on the Standard's
algorithm, which is what PR #1316 was doing. Adversarial review keeps finding the gap
between the written model and a browser.

### Option C: fix content loss only, and document the rest

Fix the four content-loss rows. Accept wrong styling on malformed input as a known
limitation in `docs/known-limitations.md`, and stop treating a styling difference on
malformed input as a review send-back.

**Pros:** smallest change; content is the part a user can't recover by restyling.
Malformed input is rare in practice (not reachable from plain Markdown).
**Cons:** the parser stays non-browser on malformed input; reviews need the stated bar to
hold.

## Lean

(2026-11-01. The library half is superseded by [Library choice](#library-choice-2026-11-27).)

**A, with selectolax, if a compiled dependency is acceptable; C otherwise.** B ends up
reimplementing the Standard by hand. C is cheap and can ship first: its four fixes are
independent of the inline-styling code, and Option A would later replace them.

The choice is the maintainer's, because A adds a runtime dependency and changes output on
malformed input.

## Library choice (2026-11-27)

The maintainer chose option A on 2026-11-01 and left the library open until three checks
were done for selectolax: lexbor's memory-safety and CVE history, the maintainer bus factor,
and installed size. This section runs those checks and the same ones for every candidate.
Every measurement is static and local (scratch venvs, CPython 3.14.5, macOS). None goes
through `html_to_ast` or the Docs API.

### Tree conformance

There are 70 inputs: every row of the defect table above, every input added on #1329 since,
and cases the walker depends on (`<pre>` leading newline, CRLF, character references, NUL,
foster-parented table text, `<template>`, `<dialog>`, raw-text elements, foreign content).
Each was parsed by each library and its `<body>` tree compared with html5lib's, after
merging adjacent text nodes. On every input, selectolax, justhtml and markupever build the
same tree as html5lib, apart from two settings that are options, not conformance gaps:

- `<noscript>`: selectolax and html5lib parse it with scripting off (content as elements);
  justhtml and markupever default to scripting on (content as raw text). justhtml takes
  `scripting_enabled=`.
- justhtml **sanitizes by default** (`JustHTML(html)` drops comments, unsafe URLs and more).
  The walker must call `JustHTML(html, sanitize=False)`.

Conformance doesn't separate the candidates. Safety and scaling do.

### Scaling on adversarial input

`html_to_ast` runs on whatever HTML a caller sends, raw HTML in Markdown included, so
parse time has to stay linear in the input. Seconds per parse, one run each:

| Input | selectolax | justhtml | markupever | `develop` today |
|---|---|---|---|---|
| 427 KB well-formed document (above) | 0.016 | 0.50 | — | 0.84 |
| QA round 6 formatting input, n = 32,000 (96,000 tags) | 0.027 | 0.93 | — | — |
| `<ul><li>` × 10,000 (nesting depth) | 1.1 | 0.34 | 2.7 | 2.1 |
| `<ul><li>` × 40,000 (330 KB) | **46.8** | 1.2 | — | — |
| `<div>` × 40,000 | 6.3 | 0.49 | — | — |
| one `<p>` with 40,000 attributes (340 KB) | 6.0 | 0.049 | 0.72 | 0.080 |
| one `<p>` with 200,000 attributes (1.4 MB) | **> 4.5 min, killed** | — | — | — |

selectolax is quadratic in nesting depth and in attribute count. At 40,000 attributes,
doubling the input costs it 5×. justhtml is linear on every input tried. markupever
(html5ever) is quadratic in both, more mildly. selectolax releases the GIL while it parses,
so a slow parse stalls only its own thread. justhtml holds the GIL, but
`content._convert_doc_content` already runs the conversion off the event loop.

Browsers bound nesting by capping tree depth (Chromium stops nesting at 512). Whichever
library is picked, the walker should keep an explicit depth cap, as `md_to_html` does with
`_MAX_NESTING`, and must not recurse on the Python stack.

### Memory safety and maintenance

| | selectolax (lexbor, C) | justhtml (pure Python) | markupever (html5ever, Rust) | html5lib |
|---|---|---|---|---|
| Net installed size | 7.3 MB | 2.0 MB | 1.9 MB | 1.5 MB (+ `six`, `webencodings`) |
| Runtime dependencies | none | none | none | 2 |
| License | MIT (lexbor Apache-2.0) | MIT | MIT | MIT |
| Commits by top contributor | selectolax 703 of 753; lexbor 906 of 1,052 | 2,045 of 2,062 | 229 of 284 | spread; last push 2026-04 |
| Popularity (GitHub stars) | 1.7k (lexbor 2.1k) | 1.2k | 41 | 1.2k |
| Releases | 1.0.2, 2026-10-22 | 98 releases since 2025-12, now 3.18.0 | 0.5.1 | 1.1, 2020 |
| Known advisories on the parse path | 2 lexbor CVEs (below) | 1 of 10, recursion DoS, fixed in 1.10.0 | none | none (2 old ones are in its serializer) |

**lexbor.** CVE-2026-29078 (ISO-2022-JP encoder, out-of-bounds write) and CVE-2026-29079
(fragment parser type confusion) are both high and fixed in lexbor 2.7.0. selectolax
1.0.2 pins lexbor at `f4cbbcd` (2026-09-28), 109 commits past 2.7.0, so it has both fixes.
But lexbor's commit log from 2025-11-27 to 2026-11-27 has more than 20 further memory-safety
fixes with no CVE attached (use-after-free, heap and integer overflow, out-of-bounds write,
NULL dereference). Two are out-of-bounds writes on our parse path:

- `8c2d7a0` (2026-11-12): an out-of-bounds write in named character reference decoding,
  reachable with `&nGt;` or `&nLt;` at a buffer boundary.
- `de47b6b` (2026-11-12): an out-of-bounds write in attribute handling for foreign
  (SVG/MathML) elements.

Both landed after selectolax's pin (`8c2d7a0` is 12 commits past it). No selectolax release has picked them up,
so the selectolax on PyPI today parses caller HTML with them unfixed. Neither project is in
OSS-Fuzz. A C parser here means our memory safety depends on how quickly selectolax
re-vendors lexbor.

**justhtml.** It is pure Python, so a parser bug can't corrupt memory; the worst case is an
exception or CPU time. Nine of its ten advisories are in its sanitizer, Markdown output,
CSS selectors or linkifier, none of which the walker would call. The tenth, a recursion
DoS on deep nesting, was fixed in 1.10.0. It is tested against the html5lib tree-construction
tests. Its costs are a single maintainer, three major versions in 2026 (it needs a `<4` upper
bound and a review at each major), and parsing about 30× slower than selectolax, still faster
than `develop`'s own parser on the same document.

**markupever and html5lib.** Both are ruled out. markupever is memory-safe but has three
contributors and 41 stars, and it is quadratic in depth. html5lib is unmaintained and was
already measured superlinear above.

### Decision

**Decided (maintainer, 2026-11-27): justhtml**, pinned `justhtml>=3.18,<4`, called with `sanitize=False`, under a walker
with an explicit depth cap. The new information since 2026-11-01 reverses the lean:
selectolax's speed matters less than the fact that it is quadratic on two simple inputs
and that the release on PyPI today carries unfixed out-of-bounds writes on our parse path.
justhtml is linear everywhere tried, memory-safe, has no dependencies and is 2 MB.

The trade-off being accepted is a single maintainer who ships major versions often. If that
becomes unacceptable, the fallback is selectolax with an input-size and depth pre-check ahead of
it, plus a standing check that each selectolax release has re-vendored lexbor's HTML fixes.

## Decided alongside: #1231 scope

PR #1316 stops. #1231 ships as round 0's tag mapping only, on `develop`'s existing
inline-styling mechanism: a new tag behaves on malformed input exactly as `<s>` does on
`develop`. That is the review bar. A difference on malformed input that `<s>` also has is
this decision's ticket, not a send-back.
