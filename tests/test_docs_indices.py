"""Tests for docs/indices.py — Google Docs character-index helpers."""

from mcp_gee_sweet.tools.docs.indices import _collect_doc_paragraphs


def _build_doc_body(paragraph_runs: list[list[str]]) -> tuple[dict, list[tuple[int, str]]]:
    """Build a synthetic Docs API body from a list of paragraphs, each a list of
    textRun content strings (the last run of a paragraph should end in "\\n",
    matching how the real API terminates a paragraph). Returns (doc, paragraphs)
    where paragraphs is [(start_index, concatenated_text), ...] for computing
    expected offsets in tests without hand-counting characters."""
    idx = 1
    content = []
    paragraphs = []
    for runs in paragraph_runs:
        para_start = idx
        elements = []
        for text in runs:
            elements.append(
                {"startIndex": idx, "endIndex": idx + len(text), "textRun": {"content": text}}
            )
            idx += len(text)
        content.append(
            {"startIndex": para_start, "endIndex": idx, "paragraph": {"elements": elements}}
        )
        paragraphs.append((para_start, "".join(runs)))
    return {"body": {"content": content}}, paragraphs


class TestCollectDocParagraphs:
    def test_single_run_paragraph(self):
        doc, paragraphs = _build_doc_body([["Hello world\n"]])
        result = list(_collect_doc_paragraphs(doc["body"]["content"]))
        assert result == [("Hello world\n", list(range(1, 13)))]

    def test_multi_run_paragraph_indices_stay_contiguous(self):
        doc, _ = _build_doc_body([["Contact: ", "test@example.com", " again\n"]])
        text, indices = next(_collect_doc_paragraphs(doc["body"]["content"]))
        assert text == "Contact: test@example.com again\n"
        assert indices == list(range(1, 1 + len(text)))

    def test_missing_start_index_carries_offset_forward_instead_of_dropping(self):
        # Regression: the Docs API doesn't always populate a ParagraphElement's
        # startIndex (observed on a document's very first element). The old
        # implementation silently dropped any run missing it; this run's index
        # must instead be derived from the paragraph's own startIndex.
        doc = {
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "paragraph": {
                            "elements": [{"textRun": {"content": "no index\n"}}],
                        },
                    }
                ]
            }
        }
        text, indices = next(_collect_doc_paragraphs(doc["body"]["content"]))
        assert text == "no index\n"
        assert indices == list(range(1, 1 + len(text)))

    def test_missing_start_index_at_both_levels_defaults_to_document_start(self):
        # Regression: Google Docs body content is never index 0 — when the
        # very first element of a document omits startIndex at both the
        # paragraph and its first run (the actual documented quirk), the
        # fallback must be 1, not 0.
        doc = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [{"textRun": {"content": "no index anywhere\n"}}],
                        },
                    }
                ]
            }
        }
        text, indices = next(_collect_doc_paragraphs(doc["body"]["content"]))
        assert text == "no index anywhere\n"
        assert indices == list(range(1, 1 + len(text)))

    def test_astral_character_advances_offset_by_two_utf16_units(self):
        # Regression: Docs API indices are UTF-16 code units. "😀" (U+1F600) is
        # one Python character but a surrogate pair (2 units) in UTF-16 — the
        # character immediately after it must land 2 units past its own index,
        # not 1.
        doc = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [{"startIndex": 1, "textRun": {"content": "hi 😀 bye\n"}}],
                        },
                    }
                ]
            }
        }
        text, indices = next(_collect_doc_paragraphs(doc["body"]["content"]))
        emoji_pos = text.index("😀")
        assert indices[emoji_pos + 1] == indices[emoji_pos] + 2

    def test_recurses_into_table_cells(self):
        doc = {
            "body": {
                "content": [
                    {
                        "startIndex": 1,
                        "endIndex": 2,
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {
                                            "content": [
                                                {
                                                    "paragraph": {
                                                        "elements": [
                                                            {
                                                                "startIndex": 3,
                                                                "endIndex": 10,
                                                                "textRun": {
                                                                    "content": "cell one\n"
                                                                },
                                                            }
                                                        ]
                                                    }
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        },
                    }
                ]
            }
        }
        result = list(_collect_doc_paragraphs(doc["body"]["content"]))
        assert result == [("cell one\n", list(range(3, 12)))]

    def test_skips_non_text_paragraph_elements(self):
        doc = {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [
                                {"startIndex": 1, "endIndex": 2, "pageBreak": {}},
                                {
                                    "startIndex": 2,
                                    "endIndex": 8,
                                    "textRun": {"content": "text\n"},
                                },
                            ]
                        }
                    }
                ]
            }
        }
        result = list(_collect_doc_paragraphs(doc["body"]["content"]))
        assert result == [("text\n", [2, 3, 4, 5, 6])]
