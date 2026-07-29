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

from markdown.extensions.toc import slugify as _markdown_toc_slugify

_STRIP_CHARS = re.compile(r"[^\w\s-]", re.UNICODE)
_WHITESPACE_RUN = re.compile(r"\s+")
_TRAILING_DEDUP_SUFFIX = re.compile(r"-(\d+)$")
_WORD_CHARS = re.compile(r"[a-z0-9]+")


def _github_style_slugify(text: str) -> str:
    """GitHub's markdown heading-anchor convention: lowercase, strip
    punctuation (keeping any literal hyphen already present), and turn each
    run of whitespace into a matching-length run of hyphens — consecutive
    hyphens are NOT collapsed (" - " -> "---", confirmed against issue #409's
    own real example). No known maintained Python package reproduces this;
    GitHub's own reference implementation (`github-slugger`) is JS-only."""
    slug = text.lower()
    slug = _STRIP_CHARS.sub("", slug)
    return _WHITESPACE_RUN.sub(lambda m: "-" * len(m.group(0)), slug)


# One callable per known slugification scheme. The GitLab/Kramdown-style
# hyphen-collapsing convention is delegated to python-markdown's own `toc`
# extension slugify (already a dependency of this project — see _md_to_html
# above) rather than hand-rolled: confirmed live it collapses "A - Approved"
# -> "a-approved", matching that convention. GitHub's non-collapsing
# convention has no known off-the-shelf Python equivalent, so it stays
# hand-rolled. Order doesn't affect correctness — a real match must land in
# exactly one scheme's slug list for a well-formed document — only which
# scheme wins a pathological tie.
_SLUGIFY_FUNCS = [
    _github_style_slugify,
    lambda text: _markdown_toc_slugify(text, "-"),
]


def _slugs_with_dedup(heading_texts: list[str], slugify_func) -> list[str]:
    """Slugify every heading, appending a numeric -1, -2, ... suffix to the
    second and later occurrence of an identical base slug — both GitHub and
    GitLab disambiguate repeated headings this way, leaving the first
    occurrence bare. (python-markdown's own toc-extension dedup instead uses
    '_1', '_2' — deliberately not reused here, since it doesn't match either
    GitHub's or GitLab's actual convention.)"""
    seen: dict[str, int] = {}
    slugs = []
    for text in heading_texts:
        base = slugify_func(text)
        count = seen.get(base, 0)
        seen[base] = count + 1
        slugs.append(base if count == 0 else f"{base}-{count}")
    return slugs


def _normalize_tokens(text: str) -> tuple[str, ...]:
    return tuple(_WORD_CHARS.findall(text.lower().replace("-", " ")))


def resolve_heading_anchor(anchor: str, heading_texts: list[str]) -> int | None:
    """Return the index into heading_texts that `anchor` (a '#slug' fragment,
    leading '#' optional) refers to, or None if no heading matches with
    reasonable confidence.

    Tries each known slugification scheme against the full heading list
    (with duplicate-heading disambiguation applied) and accepts the first
    exact match. Falls back to comparing normalized word tokens — stripping
    a trailing '-N' disambiguation suffix from the anchor first — for slugs
    that don't exactly match a known scheme's output but clearly denote the
    same words.
    """
    anchor = anchor.lstrip("#")
    if not anchor or not heading_texts:
        return None

    # TODO(#409 follow-up): this cascading try-each-scheme-then-fall-back-to-
    # fuzzy-tokens approach is a first pass at "support multiple slugifiers
    # without needing to know which one produced a given anchor." Revisit for
    # a more precise/efficient mechanism — e.g. resolving the scheme once per
    # document from the first anchor that disambiguates it, instead of
    # re-deriving every scheme's full slug list per anchor.
    for slugify_func in _SLUGIFY_FUNCS:
        slugs = _slugs_with_dedup(heading_texts, slugify_func)
        if anchor in slugs:
            return slugs.index(anchor)

    anchor_base = _TRAILING_DEDUP_SUFFIX.sub("", anchor)
    anchor_tokens = _normalize_tokens(anchor_base)
    if not anchor_tokens:
        return None
    for i, text in enumerate(heading_texts):
        if _normalize_tokens(text) == anchor_tokens:
            return i
    return None
