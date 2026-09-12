"""Google Docs character-index helpers."""

from collections.abc import Iterator
from typing import Any


def utf16_len(text: str) -> int:
    """Return the number of UTF-16 code units in ``text``."""
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text)


def decode_code_run_text(content: str, text_style: dict[str, Any]) -> str:
    """Reverse emitter.py's write-side "\\n" -> "\\v" substitution for a
    multi-line fenced code block's *internal* line breaks (issue #719).

    Every site that reads a textRun's own content straight off the raw
    Docs API response needs this, not just doc_to_ast.py's own read path —
    get_doc_structure and find_in_doc build their text the same way and
    would otherwise leak a literal "\\v" (U+000B) with nothing indicating
    why (issue #731). Scoped to a Courier-New-styled run specifically, the
    only place the substitution is ever written, so it can't misinterpret
    an unrelated genuine soft break from insert_softbreak_paragraph."""
    if text_style.get("weightedFontFamily", {}).get("fontFamily") == "Courier New":
        return content.replace("\v", "\n")
    return content


def _collect_doc_paragraphs(content: list[dict[str, Any]]) -> Iterator[tuple[str, list[int]]]:
    """Walk document body content, recursing into table cells, yielding each
    paragraph's text paired with a parallel list of document character indices
    (one per Python character in the text, in UTF-16 code units) — lets a
    match's in-paragraph span be translated back into document offsets usable
    with style_doc_range.

    A generator so a caller (e.g. find_in_doc bounding results by max_results)
    can stop pulling early without walking the rest of a large document.

    Each ParagraphElement carries its own startIndex, but the Docs API doesn't
    always populate it (observed on a document's very first element). When
    present it's trusted directly, resyncing the running offset; when absent,
    the offset just carries forward from the paragraph's own startIndex plus
    whatever's been consumed so far, so one missing field doesn't silently
    drop that element's text the way an unconditional skip would."""
    for elem in content:
        if "paragraph" in elem:
            # Google Docs body content is never index 0 — a missing startIndex
            # here only happens on the document's very first element, which
            # implicitly starts at 1 (same convention as tables.py/emitter.py).
            offset = elem.get("startIndex", 1)
            text_parts: list[str] = []
            indices: list[int] = []
            for pe in elem["paragraph"].get("elements", []):
                start = pe.get("startIndex")
                if start is not None:
                    offset = start
                tr = pe.get("textRun")
                if tr and tr.get("content"):
                    run_text = decode_code_run_text(tr["content"], tr.get("textStyle", {}))
                    text_parts.append(run_text)
                    for ch in run_text:
                        indices.append(offset)
                        offset += utf16_len(ch)
                else:
                    end = pe.get("endIndex")
                    if end is not None:
                        offset = end
            if text_parts:
                yield "".join(text_parts), indices
        elif "table" in elem:
            for row in elem["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    yield from _collect_doc_paragraphs(cell.get("content", []))
