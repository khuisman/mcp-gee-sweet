"""Google Docs character-index helpers."""


def utf16_len(text: str) -> int:
    """Return the number of UTF-16 code units in ``text``."""
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text)
