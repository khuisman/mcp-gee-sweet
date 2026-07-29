# Design: Resolving GitHub/GitLab Heading-Anchor Links (issue #409)

## Problem

Markdown converted from GitHub/GitLab Pages-published source uses standard heading-anchor
links for internal cross-references, e.g. `[Appendix A](#appendix-a---approved-hashing-algorithms)`.
These are meaningful on the source site (which auto-generates heading slugs), but after
`create_doc`/`create_doc_from_file`/`write_doc_content` conversion, the run keeps the literal
`#slug` fragment as its `link_url` — a URL fragment that means nothing inside a Google Doc.
The link renders as a normal blue/underlined hyperlink but goes nowhere, which reads as an
error to anyone reviewing the document (worse than plain, unlinked text).

## What actually resolves it

Google Docs has its own internal-link mechanism, and the issue originally assumed it required
the `Link.headingId`/`Link.bookmarkId` API fields. Live testing (2026-07-24, see the issue
thread) found a simpler path: a Doc's own "Copy link to heading" feature produces an ordinary
HTTPS URL — `https://docs.google.com/document/d/<docId>/edit?tab=t.0#heading=h.<hash>` — and
setting that as a normal `link_url` via `style_doc_range` works as a real in-doc jump link.
No special `Link` object field is needed.

The only missing piece was *discovering* a heading's `h.xxx` id. It turns out to already be
present in every `documents.get()` response (`paragraphStyle.headingId`), confirmed live
against both `TITLE`/`SUBTITLE` and `HEADING_1`..`6` paragraphs — no `includeTabsContent`
flag or tabs-aware restructuring needed, since the default single-tab response already
carries the field. `get_doc_structure` now surfaces it.

## The harder problem: which anchor names which heading

Knowing a heading's real id isn't enough — resolving `#appendix-a---approved-hashing-algorithms`
back to the "Appendix A - Approved Hashing Algorithms" heading requires reproducing whichever
slugification algorithm the *source* site used to generate that anchor in the first place, and
that information isn't recorded anywhere in the markdown itself.

GitHub's and GitLab's conventions differ in one concrete way: GitHub does not collapse
consecutive hyphens produced by adjacent whitespace and a literal hyphen (`" - "` → `"---"`,
confirmed against this issue's own real anchor); GitLab/Kramdown-style conventions do collapse
them. Rather than trying to detect which generator produced a given document up front (usually
not knowable, and for most ordinary headings the two conventions agree anyway — they only
diverge on this hyphen-collapsing edge case), `anchors.py` tries both schemes against the
document's own real heading list and accepts whichever produces an exact match. The
GitLab-style scheme is delegated to `python-markdown`'s own `toc` extension slugify (already a
project dependency, confirmed live to collapse hyphens the same way); GitHub's non-collapsing
convention has no known off-the-shelf Python equivalent, so it's hand-rolled.

A normalized word-token comparison (stripping punctuation and a trailing `-N` disambiguation
suffix) is the last-resort fallback for a slug that doesn't exactly match either scheme but
clearly names the same heading — e.g. the heading was reworded slightly after the source
anchors were generated.

**Known limitation, flagged inline (`anchors.py`, `TODO(#409 follow-up)`):** this is a
cascading try-each-scheme-then-fall-back approach — a reasonable first pass, not the most
precise or efficient possible mechanism. A more targeted design might resolve the scheme once
per document (from the first anchor that disambiguates it) rather than re-deriving every
scheme's full slug list per anchor. Revisit if this becomes a real cost or accuracy problem in
practice.

## Product decision: an opinionated layer, not just a primitive

The original ask could have been satisfied by exposing `headingId` and leaving matching to
the calling agent (construct the URL, decide which heading an anchor means, call
`style_doc_range` itself). That was deliberately rejected in favor of resolving anchors
automatically as part of the conversion pipeline (`create_doc`/`create_doc_from_file`/
`write_doc_content`), for a fixed cost in code size:

- **Consistency at lower agent cost.** An agent converting a policy document with a dozen
  internal cross-references gets working links for free, with zero extra tool calls or
  per-link reasoning, instead of having to fetch the structure, match anchors to headings
  itself, and construct the (undocumented) jump-link URL format by hand for every single link.
- **A wrong link is worse than no link.** An anchor that matches no heading with reasonable
  confidence gets its link *stripped* (text kept, plain) rather than left dangling or guessed
  — matching the issue's own "at minimum" fallback ask. A dead-looking link reads as an error;
  a link that silently points at the wrong section is actively misleading.
- **`headingId` still surfaces on `get_doc_structure`** as a byproduct (same underlying read
  the resolution pass needs internally) — the escape hatch stays open for cases the automatic
  layer doesn't cover: docs not produced by markdown/HTML conversion through this project, or
  an agent building something custom (a live table of contents, cross-reference audit, etc.).

This "prefer an opinionated server-side layer over exposing raw primitives, when it produces
consistent results at lower agent cost" framing is a standing design principle for this
project going forward — noted here as the concrete precedent, not restated as a general rule
elsewhere in this repo.

## Scope not covered here

- **Tabs.** Every tool in this codebase (including the new resolution pass) operates only
  against a document's default tab (`t.0`) — the constructed jump-link URL hardcodes
  `tab=t.0`. No tool surface is tabs-aware today; that's a separate, not-yet-filed concern
  flagged in the issue thread, not part of this fix.
- **Duplicate-heading disambiguation order.** The `-1`, `-2`, ... suffix convention is applied
  in document order per slugification scheme, matching how GitHub/GitLab number repeated
  headings — but if a document was heavily edited after the source anchors were generated
  (headings reordered, renamed, or added), the disambiguation numbering can drift out of sync
  with the original source's numbering. The fuzzy fallback does not attempt to recover this
  case; an anchor whose exact numbered slug no longer matches falls through to being stripped.
