"""Tests for GitHub/GitLab-style heading-anchor slug resolution (issue #409)."""

from mcp_gee_sweet.tools.docs.anchors import (
    _github_style_slugify,
    compute_scheme_slugs,
    resolve_heading_anchor,
)


class TestResolveHeadingAnchor:
    def test_github_style_non_collapsed_hyphens(self):
        # Issue #409's own real-world example: " - " in the heading becomes
        # three literal hyphens in the anchor, not one.
        headings = ["Appendix A - Approved Hashing Algorithms"]
        assert resolve_heading_anchor("#appendix-a---approved-hashing-algorithms", headings) == 0

    def test_gitlab_style_collapsed_hyphens(self):
        headings = ["Appendix A - Approved Hashing Algorithms"]
        assert resolve_heading_anchor("#appendix-a-approved-hashing-algorithms", headings) == 0

    def test_leading_hash_is_optional(self):
        headings = ["Overview"]
        assert resolve_heading_anchor("overview", headings) == 0
        assert resolve_heading_anchor("#overview", headings) == 0

    def test_matches_correct_heading_among_several(self):
        headings = ["Introduction", "Appendix A - Approved Hashing Algorithms", "Appendix B"]
        assert resolve_heading_anchor("#appendix-b", headings) == 2

    def test_no_match_returns_none(self):
        headings = ["Introduction", "Appendix A"]
        assert resolve_heading_anchor("#totally-unrelated-slug", headings) is None

    def test_empty_anchor_returns_none(self):
        assert resolve_heading_anchor("#", ["Overview"]) is None
        assert resolve_heading_anchor("", ["Overview"]) is None

    def test_no_headings_returns_none(self):
        assert resolve_heading_anchor("#overview", []) is None

    def test_duplicate_headings_disambiguated_with_numeric_suffix(self):
        headings = ["Notes", "Notes", "Notes"]
        assert resolve_heading_anchor("#notes", headings) == 0
        assert resolve_heading_anchor("#notes-1", headings) == 1
        assert resolve_heading_anchor("#notes-2", headings) == 2

    def test_fuzzy_fallback_matches_reworded_punctuation(self):
        # Anchor slug doesn't exactly match either known scheme's output (e.g.
        # the heading was edited slightly after the source markdown's anchors
        # were generated), but the words are unambiguously the same.
        headings = ["Appendix A: Approved Hashing Algorithms!"]
        assert resolve_heading_anchor("#appendix-a-approved-hashing-algorithms", headings) == 0

    def test_fuzzy_fallback_does_not_guess_when_requested_occurrence_is_missing(self):
        # Only one "Notes and Caveats" heading exists, but the anchor's "-2"
        # suffix claims it's the third duplicate. Resolving to the lone
        # heading anyway would be a guess, not a confirmed match — the
        # anchor's own claimed occurrence doesn't exist, so this must decline
        # rather than silently pick the only candidate.
        headings = ["Notes and Caveats"]
        assert resolve_heading_anchor("#totally-different-notes-and-caveats-2", headings) is None
        assert resolve_heading_anchor("#notes-and-caveats-2", headings) is None

    def test_fuzzy_fallback_does_not_strip_digits_that_are_real_heading_content(self):
        # Regression for a confirmed QA finding: unconditionally treating a
        # trailing "-<digits>" as a dedup suffix let an anchor whose digits
        # were genuine heading wording ("Chapter: 2024 Edition") resolve to a
        # completely different, wrong heading ("Chapter") that only matched
        # once the (real) "2024" was stripped away.
        headings = ["Chapter: 2024 Edition", "Chapter"]
        assert resolve_heading_anchor("#chapter-2024", headings) is None

    def test_fuzzy_fallback_bare_anchor_matches_first_duplicate_occurrence(self):
        # No known scheme matches (reworded with punctuation), but the
        # bare (unsuffixed) anchor should resolve to the FIRST duplicate,
        # matching GitHub/GitLab's own convention that only the second and
        # later occurrences get a numeric suffix.
        headings = ["Notes: extra!", "Notes: extra!", "Notes: extra!"]
        assert resolve_heading_anchor("#notes-extra", headings) == 0

    def test_fuzzy_fallback_suffix_picks_correct_duplicate_occurrence(self):
        headings = ["Notes: extra!", "Notes: extra!", "Notes: extra!"]
        assert resolve_heading_anchor("#notes-extra-1", headings) == 1
        assert resolve_heading_anchor("#notes-extra-2", headings) == 2
        # Only 3 occurrences exist (indices 0-2) — a claimed 4th must not
        # fall back to guessing one of the existing three.
        assert resolve_heading_anchor("#notes-extra-3", headings) is None


class TestComputeSchemeSlugs:
    def test_precomputed_scheme_slugs_match_default_internal_computation(self):
        # A caller resolving several anchors against the same heading list
        # (issue #454) precomputes scheme_slugs once and passes it in on
        # every call — must resolve identically to the default (omitted)
        # path, which recomputes it internally.
        headings = ["Appendix A - Approved Hashing Algorithms", "Notes", "Notes"]
        scheme_slugs = compute_scheme_slugs(headings)

        for anchor in (
            "#appendix-a---approved-hashing-algorithms",
            "#appendix-a-approved-hashing-algorithms",
            "#notes",
            "#notes-1",
            "#totally-unrelated-slug",
        ):
            assert resolve_heading_anchor(anchor, headings, scheme_slugs) == resolve_heading_anchor(
                anchor, headings
            )

    def test_precomputed_scheme_slugs_still_falls_back_to_fuzzy_match(self):
        # A precomputed scheme_slugs miss must still fall through to
        # _fuzzy_match, exactly like the default (recompute-internally) path.
        #
        # "Setup/Installation" genuinely requires the fuzzy fallback: the
        # '/' is stripped by both known slugify schemes with no separator
        # left behind ("setupinstallation", no hyphen), so neither scheme's
        # slug list ever contains "setup-installation" — confirmed directly
        # against _slugs_with_dedup for both schemes before picking this
        # fixture. Only _fuzzy_match's word-token normalization (which
        # treats '/' and '-' as equivalent word breaks) resolves it.
        headings = ["Setup/Installation"]
        scheme_slugs = compute_scheme_slugs(headings)
        assert all("setup-installation" not in slugs for slugs in scheme_slugs)
        assert resolve_heading_anchor("#setup-installation", headings, scheme_slugs) == 0

    def test_stale_scheme_slugs_recomputed_rather_than_trusted(self):
        # scheme_slugs computed against a different (here: shorter) heading
        # list than the one actually passed must not be trusted as-is — a
        # length mismatch means it can't correspond to heading_texts, so
        # it's silently recomputed instead of risking a wrong-index match.
        stale = compute_scheme_slugs(["Old Heading"])
        headings = ["New Heading"]
        assert resolve_heading_anchor("#new-heading", headings, stale) == resolve_heading_anchor(
            "#new-heading", headings
        )


class TestGithubSchemeStripsOtherWhitespace:
    """#1460: the GitHub scheme hyphenated every whitespace run, where GitHub's
    own anchor (github-slugger) strips a tab, an NBSP and a heading's "<br>"
    break with no hyphen at all, so a "#pricelist" link to a heading written
    "Price\xa0List" — HTML input with `&nbsp;` — resolved to nothing."""

    def test_nbsp_and_tab_slug_separator_free(self):
        # Checked against github-slugger master: its disallowed-character regex
        # removes \t (\0-\x1F) and \xa0 (\xA0-\xA9), so GitHub's real
        # anchor for both is "pricelist".
        assert _github_style_slugify("Price\xa0List") == "pricelist"
        assert _github_style_slugify("Price\tList") == "pricelist"

    def test_issue_repro_resolves_the_nbsp_heading(self):
        assert resolve_heading_anchor("#pricelist", ["Price\xa0List"]) == 0

    def test_hard_break_heading_slug_is_separator_free(self):
        assert _github_style_slugify("Heading one\vheading two") == "heading-oneheading-two"

    def test_space_runs_still_become_matching_hyphens(self):
        assert _github_style_slugify("A - Approved") == "a---approved"
        assert _github_style_slugify("a  b") == "a--b"

    def test_slash_still_strips_with_no_separator(self):
        assert _github_style_slugify("Setup/Installation") == "setupinstallation"
