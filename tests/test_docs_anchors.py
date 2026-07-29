"""Tests for GitHub/GitLab-style heading-anchor slug resolution (issue #409)."""

from mcp_gee_sweet.tools.docs.anchors import resolve_heading_anchor


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

    def test_fuzzy_fallback_strips_trailing_dedup_suffix(self):
        headings = ["Notes and Caveats"]
        assert resolve_heading_anchor("#totally-different-notes-and-caveats-2", headings) is None
        assert resolve_heading_anchor("#notes-and-caveats-2", headings) == 0
