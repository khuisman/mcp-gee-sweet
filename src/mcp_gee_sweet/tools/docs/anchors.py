"""Resolve GitHub/GitLab-style '#slug' heading-anchor links against a Google
Doc's actual headings (issue #409).

Markdown converted from GitHub/GitLab Pages-published source keeps internal
cross-reference links as literal '#slug' URL fragments — meaningless inside a
Google Doc, since Docs has its own heading-jump-link addressing scheme
(a same-document URL containing '#heading=h.xxx', confirmed live 2026-07-24).
Resolving a slug back to the heading it named requires knowing which
slugification algorithm produced it, which isn't recorded anywhere — so this
tries the known common schemes against the doc's own heading list and accepts
whichever produces an exact match, falling back to normalized word-token
comparison when no scheme matches confidently.
"""

import re
import unicodedata

from markdown.extensions.toc import slugify as _markdown_toc_slugify

_TRAILING_DEDUP_SUFFIX = re.compile(r"-(\d+)$")
_WORD_CHARS = re.compile(r"[a-z0-9]+")


# github-slugger's strip set is generated (its script/generate-regex.js, built
# on Unicode 13.0.0) from whole general categories: Other_Number, every
# punctuation category, every symbol category, Control, Format, Unassigned,
# Private_Use, and every Separator — from which the Alphabetic binary
# property, the literal space and the literal hyphen are then removed.
# (Connector punctuation — "_" — is the one punctuation category it keeps.)
# Python's `unicodedata` exposes the categories but not the property, and the
# property's only members inside the stripped categories are the enclosed
# Latin letters (all Symbol-other), so those four ranges are spelled out
# below. The rule is expressed as categories rather than a frozen port of the
# generated regex.js because code-point assignments drift with the
# interpreter's own Unicode data as new characters are assigned.
_GITHUB_STRIP_CATEGORIES = frozenset(
    (
        "No",  # Other_Number — Python's \w kept these; GitHub strips them.
        "Pe",
        "Pf",
        "Pi",
        "Ps",
        "Po",
        "Pd",
        "Sm",
        "Sc",
        "Sk",
        "So",
        "Cc",
        "Cf",
        "Cn",
        "Co",
        "Zl",
        "Zp",
        "Zs",
    )
)
_GITHUB_ALPHABETIC_IN_STRIP_CATEGORIES = (
    (0x24B6, 0x24E9),  # circled Latin letters
    (0x1F130, 0x1F149),  # squared Latin capitals
    (0x1F150, 0x1F169),  # negative squared Latin capitals
    (0x1F170, 0x1F189),  # negative squared white Latin capitals
)


def _github_strips(ch: str) -> bool:
    """Whether github-slugger's strip set drops `ch` (see that set's comment)."""
    if ch == " " or ch == "-":
        return False
    if unicodedata.category(ch) not in _GITHUB_STRIP_CATEGORIES:
        return False
    code_point = ord(ch)
    return not any(
        start <= code_point <= end for start, end in _GITHUB_ALPHABETIC_IN_STRIP_CATEGORIES
    )


def _github_style_slugify(text: str) -> str:
    r"""GitHub's markdown heading-anchor convention (github-slugger, GitHub's
    own reference implementation): lowercase, drop every character in the
    strip set defined above, keep literal spaces and hyphens, and turn each
    space into a hyphen — consecutive hyphens are NOT collapsed (" - " ->
    "---", confirmed against issue #409's own real example; a run of spaces
    still becomes a matching-length run of hyphens, one per space).

    Stripping by category rather than Python's \w is what keeps the match
    where the two disagree: \w kept Other_Number characters ("²" in "Area in
    m²", "½") that GitHub strips, and dropped combining marks ("\u0301")
    that GitHub keeps, so a heading's real anchor resolved to nothing
    (#1482). Non-space whitespace — tab, NBSP, a heading's stored "\v" hard
    break — sits in stripped categories, matching github-slugger's own
    removal of them (#1460, #1357); the full story of the break and
    whitespace shapes lives in docs/design/heading-anchor-resolution.md.
    No known maintained Python package reproduces this; github-slugger is
    JS-only."""
    slug = text.lower()
    slug = "".join(ch for ch in slug if not _github_strips(ch))
    return slug.replace(" ", "-")


# One callable per known slugification scheme. The GitLab/Kramdown-style
# hyphen-collapsing convention is delegated to python-markdown's own `toc`
# extension slugify (already a dependency of this project — see _md_to_html
# above) rather than hand-rolled: confirmed live it collapses "A - Approved"
# -> "a-approved", matching that convention. GitHub's non-collapsing
# convention has no known off-the-shelf Python equivalent, so it stays
# hand-rolled. Order doesn't affect correctness — a real match must land in
# exactly one scheme's slug list for a well-formed document — only which
# scheme wins a pathological tie.
#
# Both schemes also touch a heading's hard break ("<br>", stored inside the
# heading text as a "\v", #1230): the GitHub scheme drops it with no separator
# (#1357), the collapsed GitLab scheme slugifies it to a single hyphen — extra
# tolerance for an anchor spelled with the separator, not a reproduction of
# GitLab's own <br> slug. The full story, including which break shapes can
# actually reach a heading, lives in docs/design/heading-anchor-resolution.md.
_SLUGIFY_FUNCS = [
    _github_style_slugify,
    lambda text: _markdown_toc_slugify(text, "-"),
]


def _slugs_with_dedup(heading_texts: list[str], slugify_func) -> list[str]:
    """Slugify every heading, keeping every slug unique the way github-slugger
    does (BananaSlug.slug): the first occurrence of a base slug is left bare,
    and every later repeat gets "-1", "-2", ... appended. Where a numbered
    form is itself already taken — by a heading literally titled that way —
    the counter keeps incrementing until the slug is free: "Pricelist", an
    NBSP-spelled "Price\xa0List" and a literal "Pricelist-1" yield "pricelist",
    "pricelist-1" and "pricelist-1-1" (#1482). (python-markdown's own
    toc-extension dedup instead uses '_1', '_2' — deliberately not reused
    here, since it doesn't match either GitHub's or GitLab's actual
    convention.)"""
    occurrences: dict[str, int] = {}
    slugs = []
    for text in heading_texts:
        slug = original = slugify_func(text)
        while slug in occurrences:
            occurrences[original] = occurrences[original] + 1
            slug = f"{original}-{occurrences[original]}"
        occurrences[slug] = 0
        slugs.append(slug)
    return slugs


def _normalize_tokens(text: str) -> tuple[str, ...]:
    return tuple(_WORD_CHARS.findall(text.lower().replace("-", " ")))


def _match_tokens_at_occurrence(
    anchor_text: str, heading_texts: list[str], occurrence: int
) -> int | None:
    """Return the index of the `occurrence`-th (0-based, in document order)
    heading whose normalized word tokens equal `anchor_text`'s, or None if
    fewer than `occurrence + 1` headings match. Never guesses among ambiguous
    duplicates by just returning the first — a caller wanting "the first
    match" passes occurrence=0 explicitly, same as any other occurrence."""
    anchor_tokens = _normalize_tokens(anchor_text)
    if not anchor_tokens:
        return None
    seen = 0
    for i, text in enumerate(heading_texts):
        if _normalize_tokens(text) == anchor_tokens:
            if seen == occurrence:
                return i
            seen += 1
    return None


def _fuzzy_match(anchor: str, heading_texts: list[str]) -> int | None:
    """Fallback for an anchor that doesn't exactly match either known
    slugification scheme's output but clearly names a heading by its words.

    Tries the anchor's own tokens as-is first — this deliberately does NOT
    assume a trailing '-<digits>' is a GitHub/GitLab dedup suffix, since it
    could just as easily be genuine heading wording (e.g. a heading literally
    titled "Chapter 2024"); stripping it unconditionally risked matching a
    different, wrong heading. Matching as-is at occurrence=0 also already
    covers the common case correctly: GitHub/GitLab give a duplicate
    heading's *first* occurrence the bare (unsuffixed) slug, so an anchor
    with no suffix naming a heading that has duplicates should resolve to
    that first occurrence, not bail out just because duplicates exist.

    Only if that literal match fails, and the anchor does end in
    '-<digits>', is the suffix treated as a dedup index and stripped — then
    that number is used to pick the correct occurrence among headings
    sharing the same normalized tokens, the same way _slugs_with_dedup
    numbers them for the exact-scheme match. This never falls back to
    "just return the first" when the requested occurrence isn't present.
    """
    match_idx = _match_tokens_at_occurrence(anchor, heading_texts, occurrence=0)
    if match_idx is not None:
        return match_idx

    m = _TRAILING_DEDUP_SUFFIX.search(anchor)
    if not m:
        return None
    anchor_base = anchor[: m.start()]
    occurrence = int(m.group(1))
    return _match_tokens_at_occurrence(anchor_base, heading_texts, occurrence=occurrence)


def compute_scheme_slugs(heading_texts: list[str]) -> list[list[str]]:
    """Precompute every known slugification scheme's full (deduped) slug
    list for `heading_texts`, once.

    This is the expensive part of resolve_heading_anchor's exact-match pass
    (deriving a whole document's slug list per scheme) — a caller resolving
    several anchors against the same, unchanging heading list (issue #454)
    should call this once and pass the result to resolve_heading_anchor's
    own `scheme_slugs` parameter for every anchor, instead of paying that
    cost again per anchor.
    """
    return [_slugs_with_dedup(heading_texts, f) for f in _SLUGIFY_FUNCS]


def resolve_heading_anchor(
    anchor: str,
    heading_texts: list[str],
    scheme_slugs: list[list[str]] | None = None,
) -> int | None:
    """Return the index into heading_texts that `anchor` (a '#slug' fragment,
    leading '#' optional) refers to, or None if no heading matches with
    reasonable confidence.

    Tries each known slugification scheme against the full heading list
    (with duplicate-heading disambiguation applied) and accepts the first
    exact match. Falls back to normalized-word-token comparison (see
    _fuzzy_match) for a slug that doesn't exactly match a known scheme's
    output but clearly denotes the same heading.

    `scheme_slugs`, if given, must be compute_scheme_slugs(heading_texts)'s
    own return value (issue #454) — lets a caller resolving many anchors
    against the same heading list skip re-slugifying it per anchor. Omit it
    (the default) to compute it internally, as before; a one-off caller
    doesn't need to know this parameter exists. A `scheme_slugs` that
    doesn't actually correspond to `heading_texts` (wrong length, e.g. a
    caller passing a value computed against a stale or different heading
    list) is recomputed rather than trusted — a mismatched-but-same-shaped
    scheme_slugs could otherwise silently resolve to the wrong heading
    index instead of raising or visibly failing.

    A genuinely ambiguous anchor can't be resolved by ordering: with
    headings "Price\xa0List" and "Pricelist", a "#pricelist" anchor names
    the first heading on GitHub and the second on GitLab, so the GitHub
    scheme, tried first, wins — documented rather than fixed in
    docs/design/heading-anchor-resolution.md (#1482).
    """
    anchor = anchor.lstrip("#")
    if not anchor or not heading_texts:
        return None

    # TODO(#409 follow-up): this cascading try-each-scheme-then-fall-back-to-
    # fuzzy-tokens approach is a first pass at "support multiple slugifiers
    # without needing to know which one produced a given anchor." Revisit for
    # a more precise mechanism — e.g. resolving the scheme once per document
    # from the first anchor that disambiguates it, rather than trying every
    # scheme against every anchor.
    if scheme_slugs is None or any(len(slugs) != len(heading_texts) for slugs in scheme_slugs):
        scheme_slugs = compute_scheme_slugs(heading_texts)

    for slugs in scheme_slugs:
        if anchor in slugs:
            return slugs.index(anchor)

    return _fuzzy_match(anchor, heading_texts)
