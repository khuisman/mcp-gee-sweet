# Decision: How `html_to_ast` Recovers From Malformed HTML

**Date:** 2026-11-01
**Status:** proposed. The maintainer picks an option; this doc records the evidence and a lean.
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

**A, with selectolax, if a compiled dependency is acceptable; C otherwise.** B ends up
reimplementing the Standard by hand. C is cheap and can ship first: its four fixes are
independent of the inline-styling code, and Option A would later replace them.

The choice is the maintainer's, because A adds a runtime dependency and changes output on
malformed input.

## Decided alongside: #1231 scope

PR #1316 stops. #1231 ships as round 0's tag mapping only, on `develop`'s existing
inline-styling mechanism: a new tag behaves on malformed input exactly as `<s>` does on
`develop`. That is the review bar. A difference on malformed input that `<s>` also has is
this decision's ticket, not a send-back.
