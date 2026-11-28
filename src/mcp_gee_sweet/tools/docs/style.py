import logging
import math
from typing import Any, Literal

from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread
from ...deprecation import deprecated_tool
from .doc_to_ast import _infer_blockquote_depth, _list_level_indent_start
from .emitter import (
    _BLOCK_SPACING_PT,
    PARAGRAPH_GAP_PT,
    _block_indents,
    _border_width,
    _has_collapse_signature,
    _indent_style_request,
    list_level_indents,
)
from .indices import isolated_bullet_run_wrap_requests, utf16_len
from .invalidation import doc_invalidating

logger = logging.getLogger(__name__)


_NAMED_STYLE_TYPES = frozenset(
    {
        "NORMAL_TEXT",
        "HEADING_1",
        "HEADING_2",
        "HEADING_3",
        "HEADING_4",
        "HEADING_5",
        "HEADING_6",
        "TITLE",
        "SUBTITLE",
    }
)


def _text_runs(para: dict) -> list[dict]:
    return [
        element["textRun"]
        for element in para.get("elements", [])
        if element.get("textRun", {}).get("content", "").strip()
    ]


def _magnitude(paragraph_style: dict, field_name: str) -> float | None:
    return paragraph_style.get(field_name, {}).get("magnitude")


def _is_block_paragraph(para: dict) -> bool:
    """Whether a NORMAL_TEXT paragraph is a block rather than body text: a quote or a
    rule (a left or bottom border), an empty line, a paragraph the emitter collapsed
    (`_has_collapse_signature`: text later added after a doc's final table takes its 1%
    line spacing, #1440), or a code block by the emitter's whole signature, since a
    paragraph merely set in Courier New is body text."""
    paragraph_style = para.get("paragraphStyle", {})
    if (
        _border_width(paragraph_style, "borderLeft")
        or _border_width(paragraph_style, "borderBottom")
        or _has_collapse_signature({"paragraph": para})
    ):
        return True
    runs = _text_runs(para)
    return not runs or (
        _magnitude(paragraph_style, "spaceAbove") == _BLOCK_SPACING_PT
        and _magnitude(paragraph_style, "spaceBelow") == _BLOCK_SPACING_PT
        and all(
            run.get("textStyle", {}).get("weightedFontFamily", {}).get("fontFamily")
            == "Courier New"
            for run in runs
        )
    )


def _is_kept_collapse(para: dict) -> bool:
    """Whether apply_theme's overwrite pass leaves a paragraph's spacing alone: one
    carrying the emitter's collapse (`_has_collapse_signature`) whose only content is its
    closing newline. Anything else in it, an inline image or text, even whitespace,
    overlaps what's around it at 1% line spacing, so it gets the theme's (PR #1647 QA
    round 2)."""
    elements = para.get("elements", [])
    only_newline = all("textRun" in element for element in elements) and "".join(
        element["textRun"].get("content", "") for element in elements
    ) in ("", "\n")
    return only_newline and _has_collapse_signature({"paragraph": para})


def _at_one_point(para: dict) -> bool:
    """Whether a paragraph's text is in the collapse's 1pt font, which a quote separator
    and the empty line before a table carry (the line after a final table doesn't)."""
    return any(
        element.get("textRun", {}).get("textStyle", {}).get("fontSize", {}).get("magnitude") == 1
        for element in para.get("elements", [])
    )


def _text_fields(run: dict) -> dict:
    ts = run.get("textStyle", {})
    fields: dict = {}
    ff = ts.get("weightedFontFamily", {}).get("fontFamily")
    if ff:
        fields["font_family"] = ff
    fs = ts.get("fontSize", {}).get("magnitude")
    if fs is not None:
        fields["font_size"] = fs
    if "bold" in ts:
        fields["bold"] = ts["bold"]
    if "italic" in ts:
        fields["italic"] = ts["italic"]
    rgb = ts.get("foregroundColor", {}).get("color", {}).get("rgbColor")
    if rgb:
        fields["color"] = {k: rgb[k] for k in ("red", "green", "blue") if k in rgb}
    return fields


def _body_style_entry(style_type: str, para: dict) -> dict:
    """The theme entry a body paragraph gives its named style. On NORMAL_TEXT, the
    spacing the emitter writes around a block or between paragraphs isn't read: that's
    what those values are on a server-written doc, and a theme carrying one would set it
    across the whole doc. A text field counts only when every run shares it: a bold
    lead-in or a code span is that run's own style, not the paragraph's.

    A paragraph carrying the emitter's collapse (`_has_collapse_signature`, of any named
    style) gives none of what the collapse wrote: not its 1% line spacing or zero
    spacing, which as a theme would overprint every line (#1440), and not a 1pt font, which
    the collapse sets on a quote separator or the empty line before a table."""
    collapsed = _has_collapse_signature({"paragraph": para})

    def spacing(field_name: str) -> float | None:
        value = _magnitude(ps, field_name)
        emitted = value in (_BLOCK_SPACING_PT, PARAGRAPH_GAP_PT)
        return None if style_type == "NORMAL_TEXT" and emitted else value

    entry: dict = {}
    ps = para.get("paragraphStyle", {})
    if not collapsed:
        if "lineSpacing" in ps:
            entry["line_spacing"] = ps["lineSpacing"]
        space_above = spacing("spaceAbove")
        if space_above is not None:
            entry["space_above"] = space_above
        space_below = spacing("spaceBelow")
        if space_below is not None:
            entry["space_below"] = space_below
    run_fields = [_text_fields(run) for run in _text_runs(para)]
    if run_fields:
        first, *rest = run_fields
        entry.update({k: v for k, v in first.items() if all(other.get(k) == v for other in rest)})
    if collapsed and entry.get("font_size") == 1:
        del entry["font_size"]
    return entry


def _read_body_styles(doc: dict) -> dict:
    """Derive a theme dict from body paragraph styles — first occurrence per named style type.

    AI-generated docs apply explicit styles to individual paragraphs and runs rather than
    setting namedStyles defaults. This function reads the actual applied styles from the body
    so the returned theme reflects what the document looks like. Subsequent paragraphs of
    the same namedStyleType with different styles are ignored (treated as intentional
    individual overrides outside the theme system).

    The first occurrence decides, explicit style or not: moving past an unstyled
    paragraph read one run's inline bold as the doc's body text (PR #1388 QA round 3).

    What the emitter writes for a block or a paragraph break isn't a theme value (PR #1388
    QA rounds 1 and 2). So NORMAL_TEXT comes from body text, not a block
    (_is_block_paragraph), and doesn't read that spacing (_body_style_entry). Only a doc
    with no body text at all takes NORMAL_TEXT from its first block with text.

    A paragraph of any other named style carrying the emitter's collapse (text added
    after a doc's final table, then made a heading) is skipped the same way, so a later
    real paragraph of that style decides; it's that style's fallback only when there is
    none (PR #1647 QA round 1).
    """
    theme: dict = {}
    seen: set[str] = set()
    fallbacks: dict[str, dict] = {}
    for elem in doc.get("body", {}).get("content", []):
        para = elem.get("paragraph")
        if not para:
            continue
        style_type = para.get("paragraphStyle", {}).get("namedStyleType")
        if style_type not in _NAMED_STYLE_TYPES or style_type in seen:
            continue
        skipped = (
            _is_block_paragraph(para)
            if style_type == "NORMAL_TEXT"
            else _has_collapse_signature({"paragraph": para})
        )
        if skipped:
            if style_type not in fallbacks and _text_runs(para):
                fallbacks[style_type] = para
            continue
        seen.add(style_type)
        entry = _body_style_entry(style_type, para)
        if entry:
            theme[style_type] = entry
    for style_type, para in fallbacks.items():
        if style_type not in seen:
            entry = _body_style_entry(style_type, para)
            if entry:
                theme[style_type] = entry
    return theme


def _read_named_styles(doc: dict) -> dict:
    """Read a theme dict from a doc's namedStyles defaults.

    Returns what was set via Format > Paragraph styles > Update X to match in the
    Google Docs UI. For docs where styles were applied directly to paragraphs without
    updating named styles, this will reflect Google's defaults rather than the doc's
    actual appearance — use _read_body_styles in that case.
    """
    theme: dict = {}
    for style in doc.get("namedStyles", {}).get("styles", []):
        style_type = style.get("namedStyleType")
        if style_type not in _NAMED_STYLE_TYPES:
            continue
        entry: dict = {}
        ts = style.get("textStyle", {})
        ff = ts.get("weightedFontFamily", {}).get("fontFamily")
        if ff:
            entry["font_family"] = ff
        fs = ts.get("fontSize", {}).get("magnitude")
        if fs is not None:
            entry["font_size"] = fs
        if "bold" in ts:
            entry["bold"] = ts["bold"]
        if "italic" in ts:
            entry["italic"] = ts["italic"]
        rgb = ts.get("foregroundColor", {}).get("color", {}).get("rgbColor")
        if rgb:
            entry["color"] = {k: rgb[k] for k in ("red", "green", "blue") if k in rgb}
        ps = style.get("paragraphStyle", {})
        if "lineSpacing" in ps:
            entry["line_spacing"] = ps["lineSpacing"]
        space_above = ps.get("spaceAbove", {}).get("magnitude")
        if space_above is not None:
            entry["space_above"] = space_above
        space_below = ps.get("spaceBelow", {}).get("magnitude")
        if space_below is not None:
            entry["space_below"] = space_below
        if entry:
            theme[style_type] = entry
    return theme


def _own_paragraph_spacing_fields(doc: dict) -> set[str]:
    """The paragraph spacing fields ("spaceAbove", "spaceBelow") a doc's NORMAL_TEXT
    sets, as a theme gives them, which a paragraph gap (#1382) would override."""
    return _spacing_fields(_read_named_styles(doc).get("NORMAL_TEXT", {}))


def _spacing_fields(entry: dict, *, explicit_zero: bool = False) -> set[str]:
    """The Docs fields a theme entry's space_above/space_below name: non-zero ones, or
    with `explicit_zero` (a theme a caller passes, where 0 is a value it asked for) any
    present. Read from a doc, 0 can't be told from the default."""
    return {
        api_field
        for key, api_field in (("space_above", "spaceAbove"), ("space_below", "spaceBelow"))
        if (key in entry if explicit_zero else entry.get(key))
    }


def _clear_paragraph_gap_requests(doc: dict, theme_fields: set[str]) -> list[dict]:
    """Requests that hand NORMAL_TEXT body paragraphs carrying the emitter's paragraph
    gap (#1382) back to the named style, for a theme that sets NORMAL_TEXT spacing
    (`theme_fields`: "spaceAbove", "spaceBelow"): a value set on the paragraph beats the
    style, so the theme's spacing wouldn't reach them. Fields named, values absent,
    resets it.

    A gap beside a table (#1427) is cleared only when the theme sets that same field: a
    table takes no spacing, so a theme spaced only below its paragraphs would leave the
    paragraph after a table on its border (PR #1434 QA round 1). It's found by place, as
    the emitter writes it: spaceAbove on the paragraph right after a table, spaceBelow
    on the one before a table's empty paragraph. A 10pt spaceAbove anywhere else isn't
    the emitter's, and stays."""
    content = doc.get("body", {}).get("content", [])
    requests = []
    for i, elem in enumerate(content):
        paragraph_style = elem.get("paragraph", {}).get("paragraphStyle", {})
        if paragraph_style.get("namedStyleType") != "NORMAL_TEXT":
            continue
        fields = []
        if (
            _magnitude(paragraph_style, "spaceAbove") == PARAGRAPH_GAP_PT
            and i > 0
            and "table" in content[i - 1]
            and "spaceAbove" in theme_fields
        ):
            fields.append("spaceAbove")
        if _magnitude(paragraph_style, "spaceBelow") == PARAGRAPH_GAP_PT and (
            "spaceBelow" in theme_fields or not _precedes_table(content, i)
        ):
            fields.append("spaceBelow")
        if fields:
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": elem["startIndex"], "endIndex": elem["endIndex"]},
                        "paragraphStyle": {},
                        "fields": ",".join(fields),
                    }
                }
            )
    return requests


def _precedes_table(content: list[dict], i: int) -> bool:
    """Whether body element `i` comes right before a table: next to it, or with only the
    empty paragraph Docs keeps before a table between them."""
    following = content[i + 1 : i + 3]
    if following and "table" in following[0]:
        return True
    return len(following) == 2 and "table" in following[1] and _paragraph_text(following[0]) == "\n"


def _paragraph_text(elem: dict) -> str | None:
    paragraph = elem.get("paragraph")
    if paragraph is None:
        return None
    return "".join(el.get("textRun", {}).get("content", "") for el in paragraph.get("elements", []))


def _add_or_clear_field(
    text_style: dict, fields: list[str], api_field: str, value: dict | None
) -> None:
    """Docs API field-mask helper: sets `api_field` to `value` in `text_style`
    when `value` is not None, or omits the key entirely while still naming
    `api_field` in `fields` when it is — the documented way to reset a
    nested message field to its API default. Confirmed for `link` via #408:
    the API rejects an empty `Link{}` object outright ("must include at
    least one type"), since that isn't a valid `Link` value, but omitting
    the key while keeping the field-mask entry clears it correctly. `fields`
    always gains `api_field` either way, so a caller must gate on whether to
    send the request on `fields` (or its own local flag), never on whether
    `text_style` itself is non-empty — a clear-only call legitimately
    produces an empty `text_style` with a non-empty `fields` list. The
    `is not None` check is deliberate, not just "falsy" — an explicitly
    passed empty dict (`{}`) is a value, not a clear request, and would
    otherwise be silently written into `text_style` as an invalid/empty
    nested object, the exact class of bug (#408) this helper exists to
    prevent (PR #778 QA round 1, finding 1).

    Mutates `text_style`/`fields` in place and returns nothing — a
    deliberate deviation from `_text_style_and_fields`'s own
    build-and-return-a-fresh-tuple convention in this same file, chosen so
    a caller can accumulate several fields (some set, some cleared) onto
    one shared `text_style`/`fields` pair across multiple calls, the way
    `content.py`'s heading-anchor code does — a return-tuple version would
    force each caller to merge dicts/lists back together itself instead
    (PR #778 QA round 1, finding 2).

    Reused by any nullable nested-message field this shape applies to (not
    just `link`) so a future one (e.g. `foreground_color: null`) doesn't
    need to hand-roll the same omit-but-mask trick inline a third time
    (issue #448) the way both `_text_style_and_fields`'s own `link_url`
    case and `content.py`'s heading-anchor link-clearing code once did.
    """
    if value is not None:
        text_style[api_field] = value
    fields.append(api_field)


def _text_style_and_fields(style: dict) -> tuple[dict, list[str]]:
    """Build a Docs API textStyle dict + field mask from a flat style dict keyed
    by bold/italic/underline/strikethrough/font_size/font_family/foreground_color/link_url.

    Shared by style_doc_range and insert_softbreak_paragraph so both tools draw
    per-run styling from the same key vocabulary and request-building logic.
    May return an empty text_style with a non-empty fields list (a
    clear-only call, e.g. link_url=None/"") — see _add_or_clear_field's own
    docstring for why a caller must gate on `fields`, not `text_style`.
    """
    text_style: dict = {}
    fields: list[str] = []
    for key in ("bold", "italic", "underline", "strikethrough"):
        if key in style:
            text_style[key] = style[key]
            fields.append(key)
    if "font_size" in style:
        text_style["fontSize"] = {"magnitude": style["font_size"], "unit": "PT"}
        fields.append("fontSize")
    if "font_family" in style:
        text_style["weightedFontFamily"] = {"fontFamily": style["font_family"]}
        fields.append("weightedFontFamily")
    if "foreground_color" in style:
        text_style["foregroundColor"] = {"color": {"rgbColor": style["foreground_color"]}}
        fields.append("foregroundColor")
    if "link_url" in style:
        link = {"url": style["link_url"]} if style["link_url"] else None
        _add_or_clear_field(text_style, fields, "link", link)
    return text_style, fields


# style_doc_range's paragraph spacing keys (#1439), each with its Docs field and whether
# zero is a valid value (a 0% line spacing isn't; 0pt of space is).
_PARAGRAPH_SPACING_KEYS = (
    ("line_spacing", "lineSpacing", False),
    ("space_above", "spaceAbove", True),
    ("space_below", "spaceBelow", True),
)


def _paragraph_spacing_and_fields(style: dict) -> tuple[dict, list[str]] | str:
    """Build a paragraphStyle dict + field mask from style_doc_range's line_spacing
    (percent, 100 = single), space_above and space_below (points) keys (#1439).

    A key given as null clears that field, so the paragraph takes its named style's
    value again: the Docs API resets a field named in `fields` but absent from the
    style (checked live). Returns an error string for a value that isn't a finite
    number, a negative one, or a line_spacing of 0.
    """
    paragraph_style: dict = {}
    fields: list[str] = []
    for key, api_field, zero_ok in _PARAGRAPH_SPACING_KEYS:
        if key not in style:
            continue
        value = style[key]
        fields.append(api_field)
        if value is None:
            continue
        # NaN and infinity pass every comparison below and aren't valid JSON numbers.
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            return f"{key} must be a number or null, got {value!r}"
        if value < 0 or (value == 0 and not zero_ok):
            limit = "zero or more" if zero_ok else "greater than zero"
            return f"{key} must be {limit}, got {value!r}"
        if key == "line_spacing":
            paragraph_style[api_field] = value
        else:
            paragraph_style[api_field] = {"magnitude": value, "unit": "PT"}
    return paragraph_style, fields


def _build_named_style_requests(style_type: str, entry: dict) -> list[dict]:
    """Build an updateNamedStyle batchUpdate request for one named style type.

    Field mask paths use snake_case (per Docs API spec) and must include
    named_style_type. The root named_style prefix is implied by the API.
    """
    ts: dict = {}
    ts_fields: list[str] = []
    if "font_family" in entry:
        ts["weightedFontFamily"] = {"fontFamily": entry["font_family"]}
        ts_fields.append("text_style.weighted_font_family")
    if "font_size" in entry:
        ts["fontSize"] = {"magnitude": entry["font_size"], "unit": "PT"}
        ts_fields.append("text_style.font_size")
    if "bold" in entry:
        ts["bold"] = entry["bold"]
        ts_fields.append("text_style.bold")
    if "italic" in entry:
        ts["italic"] = entry["italic"]
        ts_fields.append("text_style.italic")
    if "color" in entry:
        ts["foregroundColor"] = {"color": {"rgbColor": entry["color"]}}
        ts_fields.append("text_style.foreground_color")

    ps: dict = {}
    ps_fields: list[str] = []
    if "line_spacing" in entry:
        ps["lineSpacing"] = entry["line_spacing"]
        ps_fields.append("paragraph_style.line_spacing")
    if "space_above" in entry:
        ps["spaceAbove"] = {"magnitude": entry["space_above"], "unit": "PT"}
        ps_fields.append("paragraph_style.space_above")
    if "space_below" in entry:
        ps["spaceBelow"] = {"magnitude": entry["space_below"], "unit": "PT"}
        ps_fields.append("paragraph_style.space_below")

    all_fields = ts_fields + ps_fields
    if not all_fields:
        return []

    # named_style_type must always be present in the field mask
    named_style: dict = {"namedStyleType": style_type}
    if ts:
        named_style["textStyle"] = ts
    if ps:
        named_style["paragraphStyle"] = ps

    return [
        {
            "updateNamedStyle": {
                "namedStyle": named_style,
                "fields": "named_style_type," + ",".join(all_fields),
            }
        }
    ]


def _normalize_spans(spans: list[dict[str, int]]) -> list[dict[str, int]]:
    """Sorted, disjoint [startIndex, endIndex) spans; overlapping or adjacent
    spans merge into one."""
    merged: list[dict[str, int]] = []
    for span in sorted(spans, key=lambda s: (s["startIndex"], s["endIndex"])):
        if merged and span["startIndex"] <= merged[-1]["endIndex"]:
            merged[-1]["endIndex"] = max(merged[-1]["endIndex"], span["endIndex"])
        else:
            merged.append(dict(span))
    return merged


def _subtract_span(spans: list[dict[str, int]], lo: int, hi: int) -> list[dict[str, int]]:
    """Remove the [lo, hi) interval from the [startIndex, endIndex) spans."""
    out: list[dict[str, int]] = []
    for s in spans:
        if s["endIndex"] <= lo or s["startIndex"] >= hi:
            out.append(s)
            continue
        if s["startIndex"] < lo:
            out.append({"startIndex": s["startIndex"], "endIndex": lo})
        if hi < s["endIndex"]:
            out.append({"startIndex": hi, "endIndex": s["endIndex"]})
    return out


def _is_paragraph_start(doc: dict, index: int) -> bool:
    """Whether index is a paragraph's first index — the position right after
    the previous paragraph's newline, at the start of a paragraph's own text.
    #1584: Docs styles text inserted at such an index from the character
    after index (the paragraph's own first character), not from the newline
    before it, so a style-inheritance read must probe there instead. Walks
    table cells like _bold_runs_in_range does; a missing startIndex is
    carried forward from the previous item's endIndex (starting at 1), as
    _bold_runs_in_range and indices._collect_doc_paragraphs carry theirs,
    rather than defaulting every list position back to 1 — a missing field
    only happens on a document's very first element (#1606)."""

    def _walk(items: list, start: int) -> bool:
        offset = start
        for item in items or []:
            item_start = item.get("startIndex", offset)
            if item.get("paragraph") and item_start == index:
                return True
            offset = item.get("endIndex", item_start)
            for row in (item.get("table") or {}).get("tableRows") or []:
                for cell in row.get("tableCells") or []:
                    if _walk(cell.get("content") or [], item_start):
                        return True
        return False

    return _walk((doc.get("body") or {}).get("content"), 1)


# The ParagraphElement kinds that carry their own `textStyle` (Docs API v1;
# tests/test_docs_style.py pins this against the discovery document). Checked
# live for seven of them (inlineObjectElement, footnoteReference, pageBreak,
# person, dateElement, richLink, dropdown): Docs styles text inserted beside
# each from its bold, and a font request with no bold clears that bold (#1635,
# PR #1655). autoText, columnBreak and horizontalRule are assumed to behave the
# same from the schema alone, since no request inserts them.
_STYLED_ELEMENT_KINDS = (
    "textRun",
    "inlineObjectElement",
    "person",
    "richLink",
    "autoText",
    "footnoteReference",
    "dateElement",
    "dropdown",
    "pageBreak",
    "columnBreak",
    "horizontalRule",
)


def _bold_runs_in_range(doc: dict, start_index: int, end_index: int) -> list[dict[str, int]]:
    """The [startIndex, endIndex) spans of directly bold runs inside a range. #1273

    A `weightedFontFamily` update that sends no `bold` in the same request clears
    the range's direct bold (the Docs API renders the new font at weight 400), so
    `style_doc_range` reads these spans from the document first and restores
    `bold: true` over them in the same batchUpdate, after the font request.
    Only a run's own `textStyle.bold` counts — bold inherited from a named style
    is not part of the run and is not affected by the font request. Every
    ParagraphElement kind that carries a `textStyle` counts as a run, not only
    `textRun` (`_STYLED_ELEMENT_KINDS`): Docs styles inserted text from a
    directly bold inline image, person chip or footnote reference just as from
    text, and the font request clears such an element's bold as it does text's
    (#1635; which kinds were checked live and which are assumed from the
    schema is noted on `_STYLED_ELEMENT_KINDS`). Adjacent bold
    runs merge into one span, and table cells are walked with their content.
    A ParagraphElement sometimes carries no `startIndex` — the Docs API omits
    it, usually on a document's very first element — so the offset is carried
    forward from the paragraph's own start the way
    `indices._collect_doc_paragraphs` does, instead of raising a KeyError.
    """
    spans: list[dict[str, int]] = []

    def _runs_of_paragraph(para: dict, para_start: int) -> None:
        offset = para_start
        for element in para.get("elements") or []:
            text_run = element.get("textRun")
            run = next(
                (element[k] for k in _STYLED_ELEMENT_KINDS if isinstance(element.get(k), dict)),
                None,
            )
            run_start = element.get("startIndex")
            if run_start is None:
                # No startIndex on this element (usually a document's first
                # one): carry the offset forward from the paragraph's start,
                # like indices._collect_doc_paragraphs.
                run_start = offset
            run_end = element.get("endIndex")
            if run_end is None:
                run_end = run_start
                if text_run is not None:
                    for ch in text_run.get("content") or "":
                        run_end += utf16_len(ch)
                elif run is not None:
                    # Every non-text element is one index long.
                    run_end += 1
            offset = run_end
            if run is None or run_end <= run_start:
                continue
            if run_end <= start_index or run_start >= end_index:
                continue
            if not (run.get("textStyle") or {}).get("bold"):
                continue
            span_start, span_end = max(run_start, start_index), min(run_end, end_index)
            if spans and spans[-1]["endIndex"] == span_start:
                spans[-1]["endIndex"] = span_end
            else:
                spans.append({"startIndex": span_start, "endIndex": span_end})

    def _walk(items: list) -> None:
        for item in items or []:
            para = item.get("paragraph")
            if para:
                _runs_of_paragraph(para, item.get("startIndex", 1))
            for row in (item.get("table") or {}).get("tableRows") or []:
                for cell in row.get("tableCells") or []:
                    _walk(cell.get("content") or [])

    _walk((doc.get("body") or {}).get("content"))
    return spans


_BULLET_PRESET = "BULLET_DISC_CIRCLE_SQUARE"
_NUMBERED_PRESET = "NUMBERED_DECIMAL_ALPHA_ROMAN"
_LIST_SIGNATURE_FIELDS = (
    "glyphSymbol",
    "glyphType",
    "glyphFormat",
    "startNumber",
    "bulletAlignment",
)


def _preset_level_signature(preset: str, level: int) -> dict:
    """The fields createParagraphBullets gives nesting level `level` of a list made
    with `preset`, one of the two this module writes (read live, PR #1662 QA round 1),
    indents aside (`list_level_indents`)."""
    if preset == _BULLET_PRESET:
        glyph = {"glyphSymbol": "●○■"[level % 3], "glyphFormat": f"%{level}"}
    else:
        glyph_type = ("DECIMAL", "ALPHA", "ROMAN")[level % 3]
        glyph = {"glyphType": glyph_type, "glyphFormat": f"%{level}."}
    alignment = "END" if glyph.get("glyphType") == "ROMAN" else "START"
    return {**glyph, "startNumber": 1, "bulletAlignment": alignment}


def _exact_preset(list_entry: dict) -> str | None:
    """The preset `list_entry` (a doc's `lists` entry) was made with, when every level
    matches one of the two presets this module writes exactly, glyphs, numbering and
    indents alike, else None. A list nested inside an item can be taken back out only
    with a preset that remakes it as it was: a checklist, arrow glyphs or a custom
    start number would come back as one of the two (PR #1662 QA round 1)."""
    levels = list_entry.get("listProperties", {}).get("nestingLevels", [])
    if not levels:
        return None
    for preset in (_BULLET_PRESET, _NUMBERED_PRESET):
        if all(
            {f: props.get(f) for f in _LIST_SIGNATURE_FIELDS}
            == {f: _preset_level_signature(preset, level).get(f) for f in _LIST_SIGNATURE_FIELDS}
            and (_magnitude(props, "indentFirstLine"), _magnitude(props, "indentStart"))
            == list_level_indents(level)
            for level, props in enumerate(levels)
        ):
            return preset
    return None


def _body_paragraphs(doc: dict) -> list[dict]:
    """The body's top-level paragraphs in order, each with its range, bullet, quote
    depth, indents, the text indent its list gives each level up to its own
    (`text_indents`, from the doc's `lists` map as doc_to_ast reads it), its list's
    exact preset and whether its text opens with a tab. All of it is read here, from
    the document as fetched, since every request after the bullet delete moves the
    indents (#1090).

    A quote needs a left border with a width: Docs keeps the key when a border is set
    to width 0 (checked live). An unlisted quoted paragraph inside a list item counts
    its quote from the item's text indent, since its own indent holds that too
    (`_inside_quote_depth`)."""
    doc_lists = doc.get("lists", {})
    paragraphs: list[dict] = []
    for elem in doc.get("body", {}).get("content", []):
        if "paragraph" not in elem:
            continue
        para = elem["paragraph"]
        style = para.get("paragraphStyle", {})
        bullet = para.get("bullet")
        runs = [e.get("textRun", {}).get("content", "") for e in para.get("elements", [])]
        text_indents: list[float] = []
        preset = None
        if bullet:
            entry = doc_lists.get(bullet.get("listId"), {})
            levels = entry.get("listProperties", {}).get("nestingLevels", [])
            preset = _exact_preset(entry)
            for level in range(bullet.get("nestingLevel", 0) + 1):
                props = levels[level] if level < len(levels) else None
                text_indents.append(_list_level_indent_start({"nestingLevel": level}, props))
        quoted = _border_width(style, "borderLeft") > 0
        paragraph = {
            "start": elem.get("startIndex", 0),
            "end": elem.get("endIndex", 0),
            "bullet": bullet,
            "preset": preset,
            "text_indents": text_indents,
            "quoted": quoted,
            "quote_depth": 0,
            "indents": (
                _magnitude(style, "indentFirstLine") or 0,
                _magnitude(style, "indentStart") or 0,
            ),
            "leading_tab": "".join(runs).startswith("\t"),
            "style": style,
        }
        if quoted and bullet:
            paragraph["quote_depth"] = _infer_blockquote_depth(style, text_indents[-1])
        paragraphs.append(paragraph)
    # An unlisted one goes second, since it can read its quote from an item before it.
    for i, paragraph in enumerate(paragraphs):
        if paragraph["quoted"] and not paragraph["bullet"]:
            depth = _inside_quote_depth(paragraphs, i)
            if depth is None:
                depth = _infer_blockquote_depth(paragraph["style"], 0)
            paragraph["quote_depth"] = depth
    return paragraphs


def _inside_quote_depth(paragraphs: list[dict], i: int) -> int | None:
    """The quote depth of unlisted quoted paragraph `i` when it reads as a block inside
    the list item it follows (through touching unlisted paragraphs), else None. As
    doc_to_ast._ListItemContext reads a quote at an item's text indent, it's inside
    only when the list goes on after it (PR #1662 QA round 2: `- A` / `> x` is a quote
    after the list, not a block in A): the next touching listed paragraph past the
    blocks inside the same item is in a list open at the item, or nested deeper."""
    item = None
    open_lists: set = set()
    for j in range(i - 1, -1, -1):
        if paragraphs[j]["end"] != paragraphs[j + 1]["start"]:
            break
        if paragraphs[j]["bullet"]:
            if item is None:
                item = paragraphs[j]
            open_lists.add(paragraphs[j]["bullet"].get("listId"))
        elif item is not None and _block_quote_depth(paragraphs[j], item) is None:
            break
    if item is None:
        return None
    depth = _block_quote_depth(paragraphs[i], item)
    if depth is None:
        return None
    for k in range(i + 1, len(paragraphs)):
        if paragraphs[k - 1]["end"] != paragraphs[k]["start"]:
            return None
        after = paragraphs[k]
        if after["bullet"]:
            continues = after["bullet"].get("listId") in open_lists
            return depth if continues or _nesting_level(after) > _nesting_level(item) else None
        if _block_quote_depth(after, item) is None:
            return None
    return None


def _nesting_level(paragraph: dict) -> int:
    return (paragraph["bullet"] or {}).get("nestingLevel", 0)


def _block_quote_depth(block: dict, item: dict) -> int | None:
    """The quote depth unlisted paragraph `block` has as a block inside list item
    `item` (#1094), or None when it doesn't read as one. As doc_to_ast._ListItemContext
    reads one: both lines at the text indent of the item's level or a shallower one,
    plus 36pt per quote level, the item's own and any the block adds (PR #1662 QA round
    2). A quoted block has at least one; an unquoted one is at the text indent plus the
    item's quote exactly. Its text mustn't open with a tab, which createParagraphBullets
    would consume as depth."""
    first_line, start = block["indents"]
    if block["leading_tab"] or first_line != start:
        return None
    step = _block_indents(1)[1]
    for indent in item["text_indents"]:
        quote_levels, remainder = divmod(start - indent, step)
        if remainder or quote_levels < item["quote_depth"]:
            continue
        if block["quoted"] and quote_levels >= 1:
            return int(quote_levels)
        if not block["quoted"] and quote_levels == item["quote_depth"]:
            return 0
    return None


def _in_item(block: dict, item: dict) -> bool:
    """Whether unlisted paragraph `block` reads as a block inside list item `item`."""
    return _block_quote_depth(block, item) is not None


def _inside_item(paragraphs: list[dict], gap: list[int], parent: dict) -> bool:
    """Whether every paragraph of `gap` (indices, in document order) sits inside list
    item `parent`, the item just before them: a paragraph of a list nested deeper than
    `parent` whose preset can remake it (`_exact_preset`), or an unlisted block inside
    the listed paragraph just before it, `parent` or a nested one (PR #1662 QA round 1:
    a block in a nested item)."""
    holder = parent
    for g in gap:
        paragraph = paragraphs[g]
        if paragraph["bullet"]:
            if paragraph["preset"] is None or _nesting_level(paragraph) <= _nesting_level(parent):
                return False
            holder = paragraph
        elif not _in_item(paragraph, holder):
            return False
    return True


def _list_reach(paragraphs: list[dict], i: int, step: int) -> list[tuple[int, str, int]]:
    """The paragraphs of paragraph `i`'s list reached from it in direction `step` (+1
    or -1), each as (index, role, the index of the item of `i`'s list it's inside, or
    its own). Its own list's items ("item") are reached through touching paragraphs.
    So is a run of other paragraphs between two of its items (#1288) when every one of
    them is inside the item before it (`_inside_item`), which Docs numbers past: a
    paragraph of a list nested deeper than that item ("nested"; the converter writes
    `1. A` / `- a1` / `2. B` as one numbered list with a bullet list inside), or an
    unlisted block inside it ("block", #1094). The walk stops at a table, or at a run
    that isn't inside the item before it."""
    list_id = paragraphs[i]["bullet"].get("listId")
    reached: list[tuple[int, str, int]] = []
    gap: list[int] = []
    last_item = i
    j = i
    while 0 <= j + step < len(paragraphs):
        k = j + step
        before, after = (
            (paragraphs[j], paragraphs[k]) if step > 0 else (paragraphs[k], paragraphs[j])
        )
        if before["end"] != after["start"]:
            break
        bullet = paragraphs[k]["bullet"]
        if bullet and bullet.get("listId") == list_id:
            # The item a gap is inside is the one before it in the document.
            parent = last_item if step > 0 else k
            in_order = sorted(gap)
            if not _inside_item(paragraphs, in_order, paragraphs[parent]):
                break
            reached.extend(
                (g, "nested" if paragraphs[g]["bullet"] else "block", parent) for g in in_order
            )
            reached.append((k, "item", k))
            gap = []
            last_item = k
        elif bullet or paragraphs[k]["indents"][1] > 0:
            gap.append(k)
        else:
            break
        j = k
    return reached


def _zero_indent_request(start: int, end: int) -> dict:
    """deleteParagraphBullets leaves a level-N item indented 36pt * N, and
    createParagraphBullets counts that indent as depth on top of the inserted tabs,
    so re-bulleting an already-listed paragraph compounded its level (#1069,
    confirmed live). Zeroing both indents first lets the tabs alone set the level."""
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {
                "indentStart": {"magnitude": 0, "unit": "PT"},
                "indentFirstLine": {"magnitude": 0, "unit": "PT"},
            },
            "fields": "indentStart,indentFirstLine",
        }
    }


def _bullet_requests(units: list[dict], preset: str, *, barrier: bool) -> list[dict]:
    """Delete, zero the indent, insert each unit's depth-tabs, and bullet `units` (a
    contiguous span) in one createParagraphBullets call. Every position outside the
    span, and the span's own once the call has consumed the tabs, ends where it was.

    A span with no level-0 unit goes through the anchor wrap (#713), and so does one
    that needs a `barrier`: createParagraphBullets joins its range to the list of the
    paragraph just before it when the presets match, whatever the levels (confirmed
    live, #1241), so a span after a listed paragraph starts its own list (#1297)."""
    start, end = units[0]["start"], units[-1]["end"]
    requests = [
        {"deleteParagraphBullets": {"range": {"startIndex": start, "endIndex": end}}},
        _zero_indent_request(start, end),
    ]
    total_tabs = 0
    # Descending, so an insert never moves a later unit's start.
    for unit in reversed(units):
        total_tabs += unit["nesting_level"]
        if unit["nesting_level"]:
            requests.append(
                {
                    "insertText": {
                        "location": {"index": unit["start"]},
                        "text": "\t" * unit["nesting_level"],
                    }
                }
            )
    if min(u["nesting_level"] for u in units) == 0 and not barrier:
        requests.append(
            {
                "createParagraphBullets": {
                    "range": {"startIndex": start, "endIndex": end + total_tabs},
                    "bulletPreset": preset,
                }
            }
        )
    else:
        # The anchor wrap's insert and delete cancel, so positions outside the span
        # are left where the plain call leaves them.
        requests.extend(
            isolated_bullet_run_wrap_requests(start, end + total_tabs, preset, barrier=barrier)
        )
    return requests


def _nested_lists(run: list[dict]) -> list[list[dict]]:
    """The lists nested in `run` (#1288) that go back out after its one call: for
    each stretch of units inside an item, one span per nested list, from its first
    unit to its last, in document order, so a list comes before the lists nested in
    it. A span holds what is nested in it too, which the later spans (and the blocks,
    after them) take back out in turn, as emitter._top_list_requests does."""
    spans: list[list[dict]] = []
    stretch: list[dict] = []
    for unit in [*run, None]:
        if unit is not None and unit["role"] != "item":
            stretch.append(unit)
            continue
        first: dict[str, int] = {}
        last: dict[str, int] = {}
        for index, nested in enumerate(stretch):
            if nested["role"] != "nested":
                continue
            list_id = nested["existing_bullet"].get("listId")
            first.setdefault(list_id, index)
            last[list_id] = index
        for list_id in sorted(first, key=first.__getitem__):
            spans.append(stretch[first[list_id] : last[list_id] + 1])
        stretch = []
    return spans


def register(tool):
    @tool(
        annotations=ToolAnnotations(title="Style Document Range", destructiveHint=True),
        default=True,
    )
    async def style_doc_range(
        doc_id: str,
        ranges: list[dict],
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Apply paragraph and/or text styles to one or more index ranges in a Google Doc.

        Use get_doc_structure to obtain the startIndex and endIndex for each target range.
        Multiple ranges can be styled in a single call; all batchUpdate requests are
        sent together.

        Args:
            doc_id: The Google Doc file ID.
            ranges: List of range dicts. Each dict must include start_index and end_index,
                plus any combination of the style fields below:

                Paragraph style:
                  named_style_type (str): NORMAL_TEXT, HEADING_1 … HEADING_6,
                      TITLE, SUBTITLE
                  line_spacing (float | null): percent of single spacing
                      (100 = single, 115 = 1.15x, 150 = 1.5x)
                  space_above (float | null): points above the paragraph
                  space_below (float | null): points below the paragraph
                  Null for any of the three clears the paragraph's own value, so it
                  takes its named style's again. Paragraph style applies to every
                  paragraph the range touches.

                Text style:
                  bold (bool), italic (bool), underline (bool), strikethrough (bool)
                  font_size (float): size in points
                  font_family (str): font family name (e.g. "Courier New", "Consolas")
                  foreground_color (dict): {"red": 0-1, "green": 0-1, "blue": 0-1}
                  link_url (str | null): set a hyperlink (null to clear)

        Returns:
            Confirmation with docId and count of batchUpdate requests sent.

        Note:
            Setting named_style_type also clears the paragraph's existing inline text
            styles: updateParagraphStyle re-applies the named style's own text
            properties to the paragraph's runs, even when the named style written is
            the one the paragraph already had. Within one call, a range dict carrying
            named_style_type plus text-style fields is applied paragraph-style-first,
            text-style-after, so the text styles named in the same dict are applied
            after the named style's re-application — no second call is needed for
            those. A separate call only restores per-run formatting the paragraph
            already had elsewhere, and only after reading the runs to know it.
            Passing only text-style fields never takes the updateParagraphStyle path.
            Setting named_style_type likewise clears the paragraph's own line_spacing,
            space_above and space_below, except any the same range dict sets.
        """
        lc = ctx.request_context.lifespan_context
        if not ranges:
            return {"error": "ranges list is empty"}

        # Validated before any read, so a bad value costs no API call and isn't hidden
        # by a read's error (PR #1631 QA round 1).
        spacing: list[tuple[dict, list[str]]] = []
        for i, r in enumerate(ranges):
            built = _paragraph_spacing_and_fields(r)
            if isinstance(built, str):
                return {"error": f"ranges[{i}]: {built}"}
            spacing.append(built)

        # #1273: a font_family range that sends no bold in the same request
        # clears the range's direct bold, so the bold spans to restore are read
        # before the batchUpdate is built.
        font_only = [i for i, r in enumerate(ranges) if "font_family" in r and "bold" not in r]
        bold_spans: dict[int, list[dict[str, int]]] = {}
        if font_only:
            try:
                doc = await execute_in_thread(
                    lc.docs_service.documents().get(documentId=doc_id).execute,
                    lc.docs_service,
                )
            except Exception as e:
                return {"error": str(e)}
            bold_spans = {
                i: _bold_runs_in_range(doc, ranges[i]["start_index"], ranges[i]["end_index"])
                for i in font_only
            }
            # The document read predates every request in this batch, so an
            # earlier range in the same call that sets bold over text a
            # font-only range covers changes what the restore must do: a
            # bold=True range means the overlap must end up bold, and a
            # bold=False range means it must stay unbolded (#1273 review).
            for i in font_only:
                spans = bold_spans[i]
                for r in ranges[:i]:
                    if "bold" not in r:
                        continue
                    lo = max(ranges[i]["start_index"], r["start_index"])
                    hi = min(ranges[i]["end_index"], r["end_index"])
                    if lo >= hi:
                        continue
                    spans = _subtract_span(spans, lo, hi)
                    if r["bold"]:
                        spans = _normalize_spans([*spans, {"startIndex": lo, "endIndex": hi}])
                bold_spans[i] = spans

        requests = []
        for i, r in enumerate(ranges):
            rng = {"startIndex": r["start_index"], "endIndex": r["end_index"]}

            # One updateParagraphStyle carries the named style and the spacing (#1439),
            # so the spacing named here is set together with the named style's.
            paragraph_style, paragraph_fields = spacing[i]
            if "named_style_type" in r:
                paragraph_style = {"namedStyleType": r["named_style_type"], **paragraph_style}
                paragraph_fields = ["namedStyleType", *paragraph_fields]
            if paragraph_fields:
                requests.append(
                    {
                        "updateParagraphStyle": {
                            "range": rng,
                            "paragraphStyle": paragraph_style,
                            "fields": ",".join(paragraph_fields),
                        }
                    }
                )

            text_style, text_fields = _text_style_and_fields(r)

            # A link-clear-only range (link_url=null, #408) legitimately produces
            # an empty text_style with a non-empty field mask ("link") — the
            # request must still be sent, so gate on text_fields, not text_style.
            if text_fields:
                requests.append(
                    {
                        "updateTextStyle": {
                            "range": rng,
                            "textStyle": text_style,
                            "fields": ",".join(text_fields),
                        }
                    }
                )
                # Restore the direct bold the font request clears (#1273), in
                # the same batchUpdate and after the font request, so the range
                # keeps the bold it already had. A range that sends bold itself
                # is not in bold_spans and is left alone.
                for span in bold_spans.get(i, []):
                    requests.append(
                        {
                            "updateTextStyle": {
                                "range": span,
                                "textStyle": {"bold": True},
                                "fields": "bold",
                            }
                        }
                    )

        if not requests:
            return {"error": "no recognised style fields in any range"}

        try:
            with doc_invalidating(lc.doc_cache, doc_id):
                await execute_in_thread(
                    lc.docs_service.documents()
                    .batchUpdate(documentId=doc_id, body={"requests": requests})
                    .execute,
                    lc.docs_service,
                )
        except Exception as e:
            return {"error": str(e)}

        logger.debug("style_doc_range: %d requests in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "requests": len(requests)}

    @tool(annotations=ToolAnnotations(title="Style Document Table Cells", destructiveHint=True))
    async def style_doc_table_cells(
        doc_id: str,
        table_start_index: int,
        cells: list[dict],
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Apply border, padding, and background styles to table cells in a Google Doc.

        Args:
            doc_id: The Google Doc file ID.
            table_start_index: The startIndex of the table (from get_doc_structure or
                insert_doc_table).
            cells: List of cell style dicts. Each dict must include row_index and
                column_index, plus any combination of:

                background_color (dict): {"red": 0-1, "green": 0-1, "blue": 0-1}
                padding_top, padding_right, padding_bottom, padding_left (float): points
                border_color (dict): {"red": 0-1, "green": 0-1, "blue": 0-1}
                    Applies the same color to all four borders (any edge not given its
                    own border_top/right/bottom/left below).
                border_width (float): border line width in points
                border_dash_style (str): "SOLID", "DOT", "DASH", "DASH_DOT",
                    "LONG_DASH", "LONG_DASH_DOT" (default SOLID)
                border_top, border_right, border_bottom, border_left (dict): optional
                    per-edge override, each {"color": {...}, "width": float,
                    "dash_style": str}. Any field omitted from a per-edge dict falls
                    back to the uniform border_color/border_width/border_dash_style
                    above, if given (the Docs API rejects a border with non-zero width
                    and no color as "transparent", so a width-only override needs a
                    color from somewhere). An edge with no border_<side> key falls back
                    entirely to the uniform border_color/border_width/border_dash_style,
                    if given; with neither, that edge's border is left untouched.
                row_span (int): default 1
                column_span (int): default 1

        Returns:
            Confirmation with docId and count of batchUpdate requests sent.

        Example — standard data-room table style (grey header, thin border, 3.6pt padding):
            table_start_index: <from insert_doc_table>
            cells: [
              {"row_index": 0, "column_index": 0, "column_span": <num_cols>,
               "background_color": {"red": 0.953, "green": 0.953, "blue": 0.953},
               "padding_top": 3.6, "padding_right": 3.6,
               "padding_bottom": 3.6, "padding_left": 3.6,
               "border_color": {"red": 0, "green": 0, "blue": 0},
               "border_width": 0.5, "border_dash_style": "SOLID"}
            ]

        Example — signature line (bottom border only):
            cells: [
              {"row_index": 0, "column_index": 0,
               "border_bottom": {"color": {"red": 0, "green": 0, "blue": 0}, "width": 1.0}}
            ]

        For form-style column alignment (labels/values lined up without a visible
        table, since tabStops is read-only), zero padding on every cell is
        the confirmed part of the recipe; whether border_width: 0 also suppresses
        a table's default visible border is not yet verified against the live API. See
        docs/design/borderless-table-columns.md.
        """
        lc = ctx.request_context.lifespan_context
        if not cells:
            return {"error": "cells list is empty"}

        requests = []
        for cell in cells:
            table_cell_style = {}
            fields = []

            if "background_color" in cell:
                table_cell_style["backgroundColor"] = {
                    "color": {"rgbColor": cell["background_color"]}
                }
                fields.append("backgroundColor")

            for side in ("top", "right", "bottom", "left"):
                key = f"padding_{side}"
                if key in cell:
                    api_key = f"padding{side.capitalize()}"
                    table_cell_style[api_key] = {"magnitude": cell[key], "unit": "PT"}
                    fields.append(api_key)

            has_uniform_border = (
                "border_color" in cell or "border_width" in cell or "border_dash_style" in cell
            )
            uniform_border: dict | None = None
            if has_uniform_border:
                uniform_border = {}
                if "border_color" in cell:
                    uniform_border["color"] = {"color": {"rgbColor": cell["border_color"]}}
                if "border_width" in cell:
                    uniform_border["width"] = {"magnitude": cell["border_width"], "unit": "PT"}
                uniform_border["dashStyle"] = cell.get("border_dash_style", "SOLID")

            for side in ("top", "right", "bottom", "left"):
                edge_key = f"border_{side}"
                api_key = f"border{side.capitalize()}"
                if edge_key in cell:
                    edge_spec = cell[edge_key]
                    if not isinstance(edge_spec, dict):
                        return {
                            "error": f"'{edge_key}' must be a dict with optional "
                            f"'color'/'width'/'dash_style' keys, got "
                            f"{type(edge_spec).__name__}"
                        }
                    border = {}
                    if "color" in edge_spec:
                        border["color"] = {"color": {"rgbColor": edge_spec["color"]}}
                    elif uniform_border is not None and "color" in uniform_border:
                        # The Docs API rejects a border with a non-zero width and no
                        # color as "transparent" — an edge override that only sets
                        # width must still inherit a color from somewhere.
                        border["color"] = uniform_border["color"]
                    if "width" in edge_spec:
                        border["width"] = {"magnitude": edge_spec["width"], "unit": "PT"}
                    elif uniform_border is not None and "width" in uniform_border:
                        border["width"] = uniform_border["width"]
                    if "dash_style" in edge_spec:
                        border["dashStyle"] = edge_spec["dash_style"]
                    elif uniform_border is not None:
                        border["dashStyle"] = uniform_border["dashStyle"]
                    else:
                        border["dashStyle"] = "SOLID"
                    table_cell_style[api_key] = border
                    fields.append(api_key)
                elif uniform_border is not None:
                    table_cell_style[api_key] = uniform_border
                    fields.append(api_key)

            if not table_cell_style:
                continue

            requests.append(
                {
                    "updateTableCellStyle": {
                        "tableCellStyle": table_cell_style,
                        "tableRange": {
                            "tableCellLocation": {
                                "tableStartLocation": {"index": table_start_index},
                                "rowIndex": cell["row_index"],
                                "columnIndex": cell["column_index"],
                            },
                            "rowSpan": cell.get("row_span", 1),
                            "columnSpan": cell.get("column_span", 1),
                        },
                        "fields": ",".join(fields),
                    }
                }
            )

        if not requests:
            return {"error": "no style fields found in any cell"}

        try:
            with doc_invalidating(lc.doc_cache, doc_id):
                await execute_in_thread(
                    lc.docs_service.documents()
                    .batchUpdate(documentId=doc_id, body={"requests": requests})
                    .execute,
                    lc.docs_service,
                )
        except Exception as e:
            return {"error": str(e)}

        logger.debug("style_doc_table_cells: %d requests in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "requests": len(requests)}

    @tool(annotations=ToolAnnotations(title="Create Paragraph Bullets", destructiveHint=True))
    async def create_paragraph_bullets(
        doc_id: str,
        ranges: list[dict],
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Turn one or more paragraph ranges into a bulleted or numbered list, with
        explicit nesting depth.

        Wraps the Docs API's createParagraphBullets/deleteParagraphBullets
        requests:

        - createParagraphBullets is a no-op on a paragraph that's already
          part of a list — it neither changes the existing nesting level nor
          consumes any leading tab characters meant to signal a new one
          (they're left behind as literal text). Every paragraph this tool
          touches is deleteParagraphBullets'd first (harmless even if it
          wasn't previously a list item) so createParagraphBullets always
          applies to a clean, non-list paragraph. deleteParagraphBullets
          keeps a removed item's indent, which createParagraphBullets would
          read as extra depth, so the tool also zeroes each paragraph's
          indentation before bulleting it. nesting_level is therefore
          absolute: repeating the same call changes nothing.
        - createParagraphBullets has no nestingLevel field of its own — the
          API infers each paragraph's depth from its own leading tab
          characters, but only relative to whatever ELSE is included in that
          *same* call. A paragraph immediately adjacent to an existing list
          item that call doesn't also cover gets pulled back to that
          neighbor's level regardless of its own tabs (the same class of bug
          that this project's own markdown-to-Doc converter already fixed).
          To keep every requested paragraph's relative depth correct, this
          tool fetches the document, resolves each requested range to the
          paragraph(s) it covers, and — for any that are already part of a
          list — expands the affected span to include their full contiguous
          run of same-list neighbors (preserving each neighbor's own current
          nesting level unchanged). The run continues past what sits inside
          one of its items: a list nested deeper than the item, or an
          unlisted paragraph indented to the item's text. Those keep their
          own list or no list, and the items after them keep counting. A
          nested list is passed only when it uses one of the two presets
          below unchanged; any other (a checklist, custom glyphs or start
          numbers) ends the run there. A target paragraph inside such a
          nested list, kept deeper than its item, stays in that list; a
          bullet_preset other than that list's own returns an error.
          Contiguous spans sharing one bullet
          preset are then submitted as a single createParagraphBullets call
          each, applied in descending document-position order so no
          not-yet-processed span's indices are invalidated by an earlier
          span's tab insertions. A span in which every paragraph sits at
          nesting_level > 0 (no level-0 member to anchor the API's relative
          depth inference) is wrapped with a throwaway 0-tab anchor paragraph
          that is bulleted alongside the real items and then deleted, so the
          items land at their true nesting level instead of collapsing to 0
          (the same fix emitter.py carries).
        - createParagraphBullets joins its range to the list of the paragraph
          just before it when the presets match. A span right after a list
          item therefore always starts a list of its own, at the requested
          levels; to add a paragraph to an existing list, include that list's
          items in the call.
        - A quoted paragraph keeps its quote's indent on top of its list
          level's.

        Use get_doc_structure to obtain start_index/end_index for each target
        range — typically one paragraph's own startIndex/endIndex, or a
        contiguous span covering several (all promoted to the same
        nesting_level/bullet_preset). For independent depths per paragraph,
        pass one range per paragraph.

        Args:
            doc_id: The Google Doc file ID.
            ranges: List of range dicts, each with:
                start_index (int), end_index (int): from get_doc_structure —
                    must overlap at least one existing paragraph.
                bullet_preset (str, optional): "BULLET_DISC_CIRCLE_SQUARE"
                    (unordered) or "NUMBERED_DECIMAL_ALPHA_ROMAN" (ordered) —
                    the only two presets this codebase has verified live
                    (see emitter.py). The Docs API defines additional
                    glyph/numbering presets not exercised here; pass the
                    literal API enum string to use one anyway. If omitted,
                    an already-listed target paragraph keeps its existing
                    list's own style (read from the document's own `lists`
                    map) rather than silently being converted to a
                    different one; a paragraph with no existing list falls
                    back to "BULLET_DISC_CIRCLE_SQUARE".
                nesting_level (int, optional): 0 = top-level (default), 1 =
                    one level indented, etc. Must be >= 0.

        Returns:
            Confirmation with docId and count of batchUpdate requests sent.
            {"error": ...} if ranges is empty, a nesting_level is negative, a
            range doesn't overlap any paragraph, two explicitly-requested
            contiguous paragraphs specify conflicting presets, a paragraph in
            a nested list is given another preset, or the Docs API call fails.
        """
        lc = ctx.request_context.lifespan_context
        if not ranges:
            return {"error": "ranges list is empty"}
        for r in ranges:
            if r.get("nesting_level", 0) < 0:
                return {"error": f"nesting_level must be >= 0, got {r['nesting_level']}"}

        try:
            doc = await execute_in_thread(
                lc.docs_service.documents().get(documentId=doc_id).execute,
                lc.docs_service,
            )

            doc_lists = doc.get("lists", {})

            def infer_preset(bullet: dict | None) -> str | None:
                # Reads the existing list's own glyph info (not just its
                # listId/nestingLevel) so an already-listed paragraph's
                # style is preserved rather than silently overridden by
                # this tool's own default preset (#334 round 2).
                if not bullet:
                    return None
                levels = (
                    doc_lists.get(bullet.get("listId"), {})
                    .get("listProperties", {})
                    .get("nestingLevels", [])
                )
                level = bullet.get("nestingLevel", 0)
                if level >= len(levels):
                    return None
                info = levels[level]
                if "glyphType" in info:
                    return "NUMBERED_DECIMAL_ALPHA_ROMAN"
                if "glyphSymbol" in info:
                    return "BULLET_DISC_CIRCLE_SQUARE"
                return None

            paragraphs = _body_paragraphs(doc)
            index_of = {(p["start"], p["end"]): i for i, p in enumerate(paragraphs)}

            def unit(i: int, **fields: Any) -> dict:
                p = paragraphs[i]
                return {
                    "start": p["start"],
                    "end": p["end"],
                    "existing_bullet": p["bullet"],
                    "list_preset": p["preset"],
                    "quote_depth": p["quote_depth"],
                    "indents": p["indents"],
                    **fields,
                }

            requested: dict[tuple[int, int], dict] = {}
            for r in ranges:
                r_start, r_end = r["start_index"], r["end_index"]
                covered = [
                    i for i, p in enumerate(paragraphs) if p["start"] < r_end and p["end"] > r_start
                ]
                if not covered:
                    return {"error": f"no paragraph overlaps range {r_start}-{r_end}"}
                for i in covered:
                    p = paragraphs[i]
                    requested[(p["start"], p["end"])] = unit(
                        i,
                        nesting_level=r.get("nesting_level", 0),
                        preset=r.get("bullet_preset"),
                        preset_explicit="bullet_preset" in r,
                        role="item",
                    )

            # Expand each already-listed requested paragraph to its whole list (see
            # docstring), across what is inside its items (#1288). Context paragraphs
            # keep their own current nesting level and carry no explicit preset of
            # their own (resolved per run below). A context paragraph that any
            # expansion reached as inside an item stays inside it. A requested one
            # reached in a nested list stays in that list when the request keeps it
            # deeper than the item it's in (PR #1662 QA round 1: it moved into the
            # outer list and split its own); any other requested one is an item, and
            # goes where the request puts it.
            expanded: dict[tuple[int, int], dict] = dict(requested)
            for key in requested:
                i = index_of[key]
                if not paragraphs[i]["bullet"]:
                    continue
                for step in (-1, 1):
                    for k, role, parent in _list_reach(paragraphs, i, step):
                        p = paragraphs[k]
                        kkey = (p["start"], p["end"])
                        if kkey in requested:
                            req = requested[kkey]
                            stays = role == "nested" and req["nesting_level"] > _nesting_level(
                                paragraphs[parent]
                            )
                            if not stays:
                                continue
                            if req["preset_explicit"] and req["preset"] != p["preset"]:
                                return {
                                    "error": f"the paragraph at index {p['start']} is in a "
                                    "list nested in another list's item; a bullet_preset "
                                    "other than its list's own would split that list. "
                                    "Request its whole list with the new preset instead."
                                }
                            req["role"] = "nested"
                            continue
                        if kkey in expanded:
                            if role != "item":
                                expanded[kkey]["role"] = role
                            continue
                        expanded[kkey] = unit(
                            k,
                            nesting_level=_nesting_level(p),
                            preset=None,
                            preset_explicit=False,
                            role=role,
                        )

            units = sorted(expanded.values(), key=lambda u: u["start"])

            # Group touching paragraphs into runs — each run gets exactly one
            # createParagraphBullets call, since the API infers nesting level
            # relative to siblings within that one call. Only an explicit,
            # conflicting caller-specified preset breaks an otherwise-
            # touching run; an unspecified (context or defaulted) preset
            # never does, since it's resolved per-run below. Neither does a
            # paragraph inside an item, which keeps its own list's preset.
            def explicit(u: dict) -> bool:
                return u["preset_explicit"] and u["role"] == "item"

            runs: list[list[dict]] = [[units[0]]]
            for u in units[1:]:
                last = runs[-1][-1]
                conflicts = explicit(u) and explicit(last) and u["preset"] != last["preset"]
                if u["start"] == last["end"] and not conflicts:
                    runs[-1].append(u)
                else:
                    runs.append([u])

            requests: list[dict] = []
            # Runs applied in descending document-position order so one
            # run's tab insertions never invalidate a not-yet-processed
            # run's own indices — same convention as insert_doc_text.
            for run in sorted(runs, key=lambda run: run[0]["start"], reverse=True):
                explicit_presets = {u["preset"] for u in run if explicit(u)}
                if len(explicit_presets) > 1:
                    return {
                        "error": "conflicting bullet_preset values among contiguous "
                        f"paragraphs at index {run[0]['start']}"
                    }
                if explicit_presets:
                    resolved_preset = next(iter(explicit_presets))
                else:
                    resolved_preset = next(
                        (
                            p
                            for u in run
                            if u["role"] == "item"
                            and (p := infer_preset(u["existing_bullet"])) is not None
                        ),
                        "BULLET_DISC_CIRCLE_SQUARE",
                    )

                first = index_of[(run[0]["start"], run[0]["end"])]
                previous = paragraphs[first - 1] if first else None
                follows_list = bool(
                    previous and previous["end"] == run[0]["start"] and previous["bullet"]
                )
                requests.extend(_bullet_requests(run, resolved_preset, barrier=follows_list))
                # That call put what is inside the run's items in its list. Each
                # nested list goes back out with the preset that made it (the walk
                # takes in only a list one of them remakes exactly), a barrier keeping
                # it from joining the item just before it, the way
                # emitter._top_list_requests takes a nested list out (#1288). Every
                # one of these sequences ends with every position where it started.
                for span in _nested_lists(run):
                    requests.extend(_bullet_requests(span, span[0]["list_preset"], barrier=True))
                # A block inside an item goes back out last, since a nested list's
                # call bullets one inside it again, and back to its own indents.
                # Docs numbers the items after it by listId, past it (#1094).
                for u in run:
                    if u["role"] == "block":
                        rng = {"startIndex": u["start"], "endIndex": u["end"]}
                        requests.append({"deleteParagraphBullets": {"range": rng}})
                        requests.append(_indent_style_request(rng, u["indents"], border=False))
                # createParagraphBullets sets the list level's indents, dropping a
                # quoted paragraph's quote indent; its border survives (#1090).
                for u in run:
                    if u["quote_depth"] and u["role"] != "block":
                        indents = _block_indents(u["quote_depth"], item_level=u["nesting_level"])
                        requests.append(
                            _indent_style_request(
                                {"startIndex": u["start"], "endIndex": u["end"]},
                                indents,
                                border=False,
                            )
                        )

            with doc_invalidating(lc.doc_cache, doc_id):
                await execute_in_thread(
                    lc.docs_service.documents()
                    .batchUpdate(documentId=doc_id, body={"requests": requests})
                    .execute,
                    lc.docs_service,
                )
        except Exception as e:
            return {"error": str(e)}

        logger.debug("create_paragraph_bullets: %d requests in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "requests": len(requests)}

    @tool(annotations=ToolAnnotations(title="Delete Paragraph Bullets", destructiveHint=True))
    async def delete_paragraph_bullets(
        doc_id: str,
        ranges: list[dict],
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Remove list membership (bullets/numbering) from one or more paragraph
        ranges, leaving each paragraph's text and other styling untouched.
        The API keeps a nested item's indent as paragraph indentation (36pt
        per nesting level for the standard presets), so a nested item stays
        indented after its bullet is gone; a top-level item doesn't. A quoted
        item is left at its quote's indent instead, without its level's, so it
        reads back as the quote it was.

        Args:
            doc_id: The Google Doc file ID.
            ranges: List of range dicts, each with start_index and end_index
                (from get_doc_structure).

        Returns:
            Confirmation with docId and count of batchUpdate requests sent.
        """
        lc = ctx.request_context.lifespan_context
        if not ranges:
            return {"error": "ranges list is empty"}

        requests = [
            {
                "deleteParagraphBullets": {
                    "range": {"startIndex": r["start_index"], "endIndex": r["end_index"]}
                }
            }
            for r in ranges
        ]

        try:
            doc = await execute_in_thread(
                lc.docs_service.documents().get(documentId=doc_id).execute,
                lc.docs_service,
            )
            # deleteParagraphBullets sets both indents to 36pt per nesting level,
            # whatever a quote added (confirmed live), so a quoted item lost its
            # quote's indent and read back unquoted (#1090). It goes to its quote's
            # indent alone: a level's 36pt on top read back as another quote level
            # (PR #1662 QA round 1).
            for p in _body_paragraphs(doc):
                if not p["bullet"] or not p["quote_depth"]:
                    continue
                if not any(
                    p["start"] < r["end_index"] and p["end"] > r["start_index"] for r in ranges
                ):
                    continue
                requests.append(
                    _indent_style_request(
                        {"startIndex": p["start"], "endIndex": p["end"]},
                        _block_indents(p["quote_depth"]),
                        border=False,
                    )
                )

            with doc_invalidating(lc.doc_cache, doc_id):
                await execute_in_thread(
                    lc.docs_service.documents()
                    .batchUpdate(documentId=doc_id, body={"requests": requests})
                    .execute,
                    lc.docs_service,
                )
        except Exception as e:
            return {"error": str(e)}

        logger.debug("delete_paragraph_bullets: %d requests in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "requests": len(requests)}

    @tool(annotations=ToolAnnotations(title="Get Document Theme", readOnlyHint=True))
    async def get_doc_theme(
        doc_id: str,
        source: Literal["body", "named_styles", "both"] = "body",
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Read a Google Doc's theme: from its actual paragraph styles (source="body",
        the default), from its named style defaults (source="named_styles"), or both.

        source="body" scans the document body and reads the style of the first paragraph found for
        each named style type (NORMAL_TEXT, HEADING_1 through HEADING_6, TITLE, SUBTITLE).
        Text-level fields (font_family, font_size, bold, italic, color) are the ones every
        non-empty text run in that paragraph shares, so a bold lead-in isn't reported;
        paragraph-level fields (line_spacing, space_above, space_below) come from the
        paragraph's paragraphStyle. A named style type that doesn't appear in the body, or
        whose first paragraph has no explicit style, is left out.

        NORMAL_TEXT's first paragraph is the first of body text: a quote, a rule, a code
        block or an empty line is skipped, unless the doc has no body text, and then the
        first of them with text is used. Its space_above and space_below leave out 8pt
        and 10pt, the spacing a Markdown or HTML write puts around blocks and between
        paragraphs. Text added after a doc's final table, where a write leaves an empty
        paragraph at 1% line spacing with no spacing, is skipped too, whatever its named
        style: a later paragraph of the same style decides, and only when there is none
        is it read, giving its font but no line spacing, spacing or 1pt font.

        Subsequent paragraphs of the same named style type that differ in style are
        ignored — they are treated as intentional individual overrides outside the theme.

        source="named_styles" reads the named style defaults set via Format > Paragraph
        styles > Update X to match in the Google Docs UI, which paragraphs with no
        explicit overrides inherit. Most docs leave them at Google's defaults even when
        paragraphs look custom, since people usually format text directly; then this
        returns Google's defaults (Arial/Roboto etc.), not what the doc looks like. Only
        entries with at least one non-default field are included.

        Use "body" when styles were applied directly to paragraphs (the common case),
        and "named_styles" when the human set named style defaults explicitly. "both"
        returns the two side by side: if they agree, named styles are in sync with the
        content; if they differ, styles were applied directly to paragraphs without
        updating the named style definitions.

        A "body" or "named_styles" result is suitable for passing directly to apply_theme.

        Args:
            doc_id: The Google Doc file ID.
            source: "body" (default), "named_styles", or "both".

        Returns:
            For "body" or "named_styles", a theme dict keyed by named style type, empty
            if no explicit styles are found. For "both", {"body": <theme dict>,
            "named_styles": <theme dict>}.
        """
        if source not in ("body", "named_styles", "both"):
            return {"error": f"source must be 'body', 'named_styles' or 'both', got {source!r}"}
        lc = ctx.request_context.lifespan_context
        try:
            doc = await execute_in_thread(
                lc.docs_service.documents().get(documentId=doc_id).execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}
        if source == "body":
            return _read_body_styles(doc)
        if source == "named_styles":
            return _read_named_styles(doc)
        return {"body": _read_body_styles(doc), "named_styles": _read_named_styles(doc)}

    @tool(annotations=ToolAnnotations(title="Get Document Named Styles", readOnlyHint=True))
    @deprecated_tool(
        use="`get_doc_theme` with `source='named_styles'`",
        removed_in="the next feature release",
    )
    async def get_doc_named_styles(
        doc_id: str,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Read a Google Doc's named style defaults and return them as a theme dict.

        Named styles are set via Format > Paragraph styles > Update X to match in the
        Google Docs UI. They define the default appearance for each style type and are
        inherited by paragraphs that have no explicit overrides.

        Most docs leave named styles at Google's defaults even when paragraphs look
        custom — because humans usually format text directly without updating named styles.
        In that case this tool returns Google's defaults (Arial/Roboto etc.), which may
        not reflect the doc's actual appearance. Use get_doc_theme to read what the doc
        actually looks like based on applied paragraph styles.

        Calling both tools and comparing results is useful: if they agree, named styles
        are in sync with actual content; if they differ, styles were applied directly to
        paragraphs without updating named style definitions.

        Args:
            doc_id: The Google Doc file ID.

        Returns:
            Theme dict keyed by named style type. Only entries with at least one
            non-default field are included. Returns an empty dict if named styles
            are at Google's defaults.
        """
        lc = ctx.request_context.lifespan_context
        try:
            doc = await execute_in_thread(
                lc.docs_service.documents().get(documentId=doc_id).execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}
        return _read_named_styles(doc)

    @tool(annotations=ToolAnnotations(title="Apply Document Theme", destructiveHint=True))
    async def apply_theme(
        doc_id: str,
        theme: dict,
        overwrite: bool = False,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Apply a theme dict to a Google Doc by updating its named style definitions.

        By default (overwrite=False), theme entries are applied as document-level named
        style defaults via updateNamedStyle. Paragraphs that have explicit individual style
        overrides are unaffected — their styles take precedence over the named style
        defaults. This preserves intentional per-paragraph variations (e.g. a section
        deliberately styled in a different colour). One exception: a NORMAL_TEXT entry
        with space_above or space_below replaces the 10pt space below a paragraph that
        a Markdown or HTML write leaves between paragraphs, so the theme's spacing shows.

        For AI-generated docs where all content uses explicit paragraph/run styles, the
        default mode updates the named style definitions but does not visually change
        existing content. New paragraphs added without explicit styles will inherit the
        updated named style defaults.

        Set overwrite=True to also apply the theme directly to all existing paragraphs,
        overwriting their current styles including any individual overrides. An empty
        line that a Markdown or HTML write shrank to nearly no height (between two quotes,
        before a table, or after a doc's final table) keeps its spacing and its 1pt font,
        or it would show as a blank line or push a blank last page; anything put in one
        (text or an image) gets the theme's spacing.

        Theme entry keys (NORMAL_TEXT, HEADING_1-6, TITLE, SUBTITLE). Each entry can
        include (all optional):
          font_family (str), font_size (float, points), bold (bool), italic (bool),
          color (dict {"red": 0-1, "green": 0-1, "blue": 0-1}),
          line_spacing (float, 100=single, 115=1.15x, 150=1.5x),
          space_above (float, points), space_below (float, points)

        An optional "table" key applies styling to every table currently in the document:
          border_color (dict), border_width (float, points),
          border_dash_style (str, default "SOLID"),
          border_top, border_right, border_bottom, border_left (dict): optional
              per-edge override, each {"color": {...}, "width": float, "dash_style": str}.
              Any field omitted from a per-edge dict falls back to the uniform
              border_color/border_width/border_dash_style above, if given (the Docs API
              rejects a border with non-zero width and no color as "transparent", so a
              width-only override needs a color from somewhere). An edge with no
              border_<side> key falls back entirely to the uniform border_color/
              border_width/border_dash_style, if given.
          cell_padding (float, points — all four sides),
          header_background (dict) — first row only

        Args:
            doc_id: The Google Doc file ID.
            theme: Theme dict. See above for schema.
            overwrite: If True, also apply styles directly to existing paragraphs,
                overwriting individual per-paragraph style overrides.

        Returns:
            Confirmation with docId and count of batchUpdate requests sent.
        """
        lc = ctx.request_context.lifespan_context

        named_style_keys = {k: v for k, v in theme.items() if k in _NAMED_STYLE_TYPES}
        table_style = theme.get("table")

        if not named_style_keys and not table_style:
            return {"error": "theme contains no recognised style keys"}

        requests = []

        # Always update named style definitions for each theme entry
        for style_type, entry in named_style_keys.items():
            requests.extend(_build_named_style_requests(style_type, entry))

        normal_text = named_style_keys.get("NORMAL_TEXT", {})
        sets_paragraph_spacing = "space_above" in normal_text or "space_below" in normal_text

        # Fetch the doc only when needed (overwrite mode, table styling, or paragraph gaps)
        doc: dict | None = None
        if overwrite or table_style or sets_paragraph_spacing:
            try:
                doc = await execute_in_thread(
                    lc.docs_service.documents().get(documentId=doc_id).execute,
                    lc.docs_service,
                )
            except Exception as e:
                return {"error": f"failed to fetch doc: {e}"}

        # Before the overwrite pass, whose own space_below on a paragraph must win.
        if sets_paragraph_spacing and doc:
            theme_fields = _spacing_fields(normal_text, explicit_zero=True)
            requests.extend(_clear_paragraph_gap_requests(doc, theme_fields))

        # When overwrite=True, also apply styles directly to all existing paragraphs
        if overwrite and named_style_keys and doc:
            for elem in doc.get("body", {}).get("content", []):
                para = elem.get("paragraph")
                if not para:
                    continue
                style_type = para.get("paragraphStyle", {}).get("namedStyleType")
                if style_type not in named_style_keys:
                    continue
                entry = named_style_keys[style_type]
                rng = {"startIndex": elem["startIndex"], "endIndex": elem["endIndex"]}
                # An empty paragraph the emitter collapsed (a quote separator, the line
                # before a table, the one after a doc's final table) keeps its collapse:
                # the theme's spacing would show it as a blank line, or bring back the
                # blank last page (PR #1647 QA round 1). Text typed into one gets the
                # theme's spacing, as insert_doc_text gives it the doc's (#1439).
                kept_collapse = _is_kept_collapse(para)

                ps: dict = {}
                ps_fields: list[str] = []
                if not kept_collapse:
                    if "line_spacing" in entry:
                        ps["lineSpacing"] = entry["line_spacing"]
                        ps_fields.append("lineSpacing")
                    if "space_above" in entry:
                        ps["spaceAbove"] = {"magnitude": entry["space_above"], "unit": "PT"}
                        ps_fields.append("spaceAbove")
                    if "space_below" in entry:
                        ps["spaceBelow"] = {"magnitude": entry["space_below"], "unit": "PT"}
                        ps_fields.append("spaceBelow")
                if ps_fields:
                    requests.append(
                        {
                            "updateParagraphStyle": {
                                "range": rng,
                                "paragraphStyle": ps,
                                "fields": ",".join(ps_fields),
                            }
                        }
                    )

                ts: dict = {}
                ts_fields: list[str] = []
                if "font_family" in entry:
                    ts["weightedFontFamily"] = {"fontFamily": entry["font_family"]}
                    ts_fields.append("weightedFontFamily")
                if "font_size" in entry and not (kept_collapse and _at_one_point(para)):
                    ts["fontSize"] = {"magnitude": entry["font_size"], "unit": "PT"}
                    ts_fields.append("fontSize")
                if "bold" in entry:
                    ts["bold"] = entry["bold"]
                    ts_fields.append("bold")
                if "italic" in entry:
                    ts["italic"] = entry["italic"]
                    ts_fields.append("italic")
                if "color" in entry:
                    ts["foregroundColor"] = {"color": {"rgbColor": entry["color"]}}
                    ts_fields.append("foregroundColor")
                if ts_fields:
                    requests.append(
                        {
                            "updateTextStyle": {
                                "range": rng,
                                "textStyle": ts,
                                "fields": ",".join(ts_fields),
                            }
                        }
                    )

        if table_style and doc:
            has_uniform_border = any(
                k in table_style for k in ("border_color", "border_width", "border_dash_style")
            )
            uniform_border: dict | None = None
            if has_uniform_border:
                uniform_border = {}
                if "border_color" in table_style:
                    uniform_border["color"] = {"color": {"rgbColor": table_style["border_color"]}}
                if "border_width" in table_style:
                    uniform_border["width"] = {
                        "magnitude": table_style["border_width"],
                        "unit": "PT",
                    }
                uniform_border["dashStyle"] = table_style.get("border_dash_style", "SOLID")

            edge_borders: dict[str, dict] = {}
            for side in ("top", "right", "bottom", "left"):
                edge_key = f"border_{side}"
                if edge_key in table_style:
                    edge_spec = table_style[edge_key]
                    if not isinstance(edge_spec, dict):
                        return {
                            "error": f"table['{edge_key}'] must be a dict with optional "
                            f"'color'/'width'/'dash_style' keys, got "
                            f"{type(edge_spec).__name__}"
                        }
                    edge_border: dict = {}
                    if "color" in edge_spec:
                        edge_border["color"] = {"color": {"rgbColor": edge_spec["color"]}}
                    elif uniform_border is not None and "color" in uniform_border:
                        # The Docs API rejects a border with a non-zero width and no
                        # color as "transparent" — a width-only override needs a color
                        # from somewhere.
                        edge_border["color"] = uniform_border["color"]
                    if "width" in edge_spec:
                        edge_border["width"] = {"magnitude": edge_spec["width"], "unit": "PT"}
                    elif uniform_border is not None and "width" in uniform_border:
                        edge_border["width"] = uniform_border["width"]
                    if "dash_style" in edge_spec:
                        edge_border["dashStyle"] = edge_spec["dash_style"]
                    elif uniform_border is not None:
                        edge_border["dashStyle"] = uniform_border["dashStyle"]
                    else:
                        edge_border["dashStyle"] = "SOLID"
                    edge_borders[side] = edge_border

            has_borders = has_uniform_border or bool(edge_borders)

            for elem in doc.get("body", {}).get("content", []):
                if "table" not in elem:
                    continue
                table_start = elem.get("startIndex")
                if table_start is None:
                    continue
                doc_table = elem["table"]
                num_rows = doc_table.get("rows", 0)
                num_cols = doc_table.get("columns", 0)
                if num_rows == 0 or num_cols == 0:
                    continue

                for r in range(num_rows):
                    cell_style: dict = {}
                    style_fields: list[str] = []

                    if r == 0 and "header_background" in table_style:
                        cell_style["backgroundColor"] = {
                            "color": {"rgbColor": table_style["header_background"]}
                        }
                        style_fields.append("backgroundColor")

                    if "cell_padding" in table_style:
                        pad = table_style["cell_padding"]
                        for side in ("Top", "Right", "Bottom", "Left"):
                            cell_style[f"padding{side}"] = {"magnitude": pad, "unit": "PT"}
                            style_fields.append(f"padding{side}")

                    if has_borders:
                        for side in ("Top", "Right", "Bottom", "Left"):
                            resolved_border = edge_borders.get(side.lower(), uniform_border)
                            if resolved_border is None:
                                continue
                            cell_style[f"border{side}"] = resolved_border
                            style_fields.append(f"border{side}")

                    if not style_fields:
                        continue

                    requests.append(
                        {
                            "updateTableCellStyle": {
                                "tableCellStyle": cell_style,
                                "fields": ",".join(style_fields),
                                "tableRange": {
                                    "tableCellLocation": {
                                        "tableStartLocation": {"index": table_start},
                                        "rowIndex": r,
                                        "columnIndex": 0,
                                    },
                                    "rowSpan": 1,
                                    "columnSpan": num_cols,
                                },
                            }
                        }
                    )

        if not requests:
            return {"error": "no style requests could be built from the given theme"}

        try:
            with doc_invalidating(lc.doc_cache, doc_id):
                await execute_in_thread(
                    lc.docs_service.documents()
                    .batchUpdate(documentId=doc_id, body={"requests": requests})
                    .execute,
                    lc.docs_service,
                )
        except Exception as e:
            return {"error": str(e)}

        logger.debug("apply_theme: %d requests in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "requests": len(requests)}
