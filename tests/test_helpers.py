import pytest

from mcp_gee_sweet.helpers import (
    _column_index_to_letter,
    _letter_to_column_index,
    _parse_a1_notation,
)


class TestColumnIndexToLetter:
    def test_single_letters(self):
        assert _column_index_to_letter(0) == "A"
        assert _column_index_to_letter(25) == "Z"

    def test_double_letters(self):
        assert _column_index_to_letter(26) == "AA"
        assert _column_index_to_letter(27) == "AB"
        assert _column_index_to_letter(51) == "AZ"
        assert _column_index_to_letter(52) == "BA"

    def test_triple_letters(self):
        assert _column_index_to_letter(702) == "AAA"


class TestLetterToColumnIndex:
    def test_single_letters(self):
        assert _letter_to_column_index("A") == 0
        assert _letter_to_column_index("Z") == 25

    def test_double_letters(self):
        assert _letter_to_column_index("AA") == 26
        assert _letter_to_column_index("AB") == 27
        assert _letter_to_column_index("AZ") == 51
        assert _letter_to_column_index("BA") == 52

    def test_case_insensitive(self):
        assert _letter_to_column_index("a") == _letter_to_column_index("A")
        assert _letter_to_column_index("aa") == _letter_to_column_index("AA")

    def test_roundtrip(self):
        for i in range(200):
            assert _letter_to_column_index(_column_index_to_letter(i)) == i


class TestParseA1Notation:
    def test_single_cell(self):
        result = _parse_a1_notation("A1")
        assert result["startColumnIndex"] == 0
        assert result["startRowIndex"] == 0
        assert result["endColumnIndex"] == 1
        assert result["endRowIndex"] == 1

    def test_range(self):
        result = _parse_a1_notation("A1:C3")
        assert result["startColumnIndex"] == 0
        assert result["startRowIndex"] == 0
        assert result["endColumnIndex"] == 3  # exclusive
        assert result["endRowIndex"] == 3  # exclusive

    def test_column_only(self):
        result = _parse_a1_notation("B")
        assert result["startColumnIndex"] == 1
        assert result["endColumnIndex"] == 2
        assert "startRowIndex" not in result

    def test_row_range_only(self):
        result = _parse_a1_notation("1:3")
        assert result["startRowIndex"] == 0
        assert result["endRowIndex"] == 3
        assert "startColumnIndex" not in result

    def test_column_range_only(self):
        result = _parse_a1_notation("A:C")
        assert result["startColumnIndex"] == 0
        assert result["endColumnIndex"] == 3  # exclusive
        assert "startRowIndex" not in result

    def test_open_ended_range(self):
        # B2:D — no end row specified; implementation fills endRowIndex from startRow
        result = _parse_a1_notation("B2:D")
        assert result["startColumnIndex"] == 1
        assert result["startRowIndex"] == 1
        assert result["endColumnIndex"] == 4  # exclusive
        assert result["endRowIndex"] == 2  # startRowIndex + 1 (single-row fallback)

    def test_multi_letter_column(self):
        result = _parse_a1_notation("AA1:AB2")
        assert result["startColumnIndex"] == 26
        assert result["endColumnIndex"] == 28  # exclusive

    def test_invalid_notation_raises(self):
        with pytest.raises(ValueError):
            _parse_a1_notation("Sheet1!A1")
