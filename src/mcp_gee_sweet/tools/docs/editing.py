import logging
from typing import Any

from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread
from .emitter import collapsed_trailing_paragraph
from .indices import utf16_len
from .invalidation import doc_invalidating
from .style import (
    _NAMED_STYLE_TYPES,
    _bold_runs_in_range,
    _is_paragraph_start,
    _text_style_and_fields,
)

logger = logging.getLogger(__name__)

# Only what collapsed_trailing_paragraph reads: each body element's range, whether
# it's a table, and the paragraph spacing; plus the revision the read saw.
_TRAILING_PARAGRAPH_FIELDS = (
    "revisionId,body/content(startIndex,endIndex,table/rows,"
    "paragraph/paragraphStyle(lineSpacing,spaceAbove,spaceBelow))"
)


def _in_body(op: dict) -> bool:
    """An insertion goes to the body unless it names a header or footer: the Docs API
    reads an empty or null segmentId as the body."""
    return not op.get("segment_id")


async def _trailing_paragraph_reset(
    docs_service, doc_id: str, sorted_ops: list[dict]
) -> tuple[dict, str | None] | None:
    """The request that gives text inserted into the collapsed paragraphs after a
    doc's final table their line spacing back, with the revision ID it was computed
    against, or None when no insertion goes there (#1439).

    The emitter collapses the paragraph after a final table
    (`_build_trailing_para_after_table_collapse`, #1100), and inserted text takes its
    1% line spacing and overprints the table. The request clears lineSpacing,
    spaceAbove and spaceBelow by naming them with no value, so the text takes its
    named style's (checked live), from the first collapsed paragraph's start to the
    body's end once the insertions have landed. It goes after every insertText, so
    its range counts all of them. Header and footer insertions neither land there nor
    move the body.

    The range comes from this read, so the caller sends the batch with the read's
    revision as `targetRevisionId`: an edit made since is then transformed against
    the batch instead of leaving the range stale (PR #1631 QA round 1).
    """
    body_ops = [op for op in sorted_ops if _in_body(op)]
    if not body_ops:
        return None
    doc = await execute_in_thread(
        docs_service.documents().get(documentId=doc_id, fields=_TRAILING_PARAGRAPH_FIELDS).execute,
        docs_service,
    )
    found = collapsed_trailing_paragraph((doc.get("body") or {}).get("content") or [])
    if found is None:
        return None
    start, end = found
    # The final paragraph's own newline can't take text, so the last index into the
    # collapsed run is end - 1.
    if not any(start <= op["index"] <= end - 1 for op in body_ops):
        return None
    shift = sum(utf16_len(op["text"]) for op in body_ops if op["index"] < start)
    added = sum(utf16_len(op["text"]) for op in body_ops)
    request = {
        "updateParagraphStyle": {
            "range": {"startIndex": start + shift, "endIndex": end + added},
            "paragraphStyle": {},
            "fields": "lineSpacing,spaceAbove,spaceBelow",
        }
    }
    return request, doc.get("revisionId")


def register(tool):
    @tool(
        annotations=ToolAnnotations(title="Insert Document Text", destructiveHint=True),
        default=True,
    )
    async def insert_doc_text(
        doc_id: str,
        insertions: list[dict],
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Insert text at one or more positions in a Google Doc.

        All indices are interpreted as positions in the document before any of
        the insertions in this call. Insertions are applied high-index-first so
        earlier indices are not shifted by later ones.

        Use get_doc_structure to obtain the correct target indices.

        Args:
            doc_id: The Google Doc file ID.
            insertions: List of insertion dicts. Required keys:
                index (int): document position to insert at.
                text (str): text to insert. "\\n" creates a new paragraph.
              Optional keys:
                segment_id (str): segmentId of the header or footer to insert into
                    (the headerId / footerId returned by create_header_or_footer).
                    Omit to insert into the document body.

        Returns:
            Confirmation with docId and count of insertions applied. When text goes
            into the collapsed empty paragraph that create_doc and the other content
            writers leave after a doc's final table, that text gets the doc's normal
            line spacing back, and the result's trailingParagraphReset is true.
        """
        lc = ctx.request_context.lifespan_context
        if not insertions:
            return {"error": "insertions list is empty"}
        try:
            sorted_ops = sorted(insertions, key=lambda x: x["index"], reverse=True)
            requests = []
            for op in sorted_ops:
                location: dict[str, Any] = {"index": op["index"]}
                if not _in_body(op):
                    location["segmentId"] = op["segment_id"]
                requests.append({"insertText": {"location": location, "text": op["text"]}})
            reset = await _trailing_paragraph_reset(lc.docs_service, doc_id, sorted_ops)
            body: dict[str, Any] = {"requests": requests}
            if reset:
                reset_request, revision_id = reset
                requests.append(reset_request)
                if revision_id:
                    body["writeControl"] = {"targetRevisionId": revision_id}
            with doc_invalidating(lc.doc_cache, doc_id):
                await execute_in_thread(
                    lc.docs_service.documents().batchUpdate(documentId=doc_id, body=body).execute,
                    lc.docs_service,
                )
        except Exception as e:
            return {"error": str(e)}
        logger.debug("insert_doc_text: %d insertions in doc %s", len(sorted_ops), doc_id)
        result: dict[str, Any] = {"docId": doc_id, "insertions": len(sorted_ops)}
        if reset:
            result["trailingParagraphReset"] = True
        return result

    @tool(
        annotations=ToolAnnotations(title="Delete Document Range", destructiveHint=True),
        default=True,
    )
    async def delete_doc_range(
        doc_id: str,
        deletions: list[dict],
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Delete one or more content ranges from a Google Doc.

        All indices are interpreted as positions in the document before any of
        the deletions in this call. Deletions are applied high-index-first so
        earlier indices are not shifted by later ones.

        Use get_doc_structure to obtain the correct start/end indices.

        Args:
            doc_id: The Google Doc file ID.
            deletions: List of {"start_index": int, "end_index": int}.
                The range [start_index, end_index) is deleted (end_index is exclusive).
                Do not include the document's final newline (last endIndex - 1).

        Returns:
            Confirmation with docId and count of deletions applied.

        Note:
            Including a paragraph's trailing paragraph mark in the deleted range
            merges that paragraph into the next one, and the merged result inherits
            the *next* paragraph's style (e.g. deleting through a NORMAL_TEXT
            paragraph's newline when the following paragraph is HEADING_1 leaves the
            surviving content styled as HEADING_1). Text inserted afterward at that
            position silently picks up the same inherited style. Follow a
            paragraph-mark-inclusive delete with an explicit updateParagraphStyle
            (style_doc_range's named_style_type, or insert_softbreak_paragraph's
            named_style_type) rather than assuming the original style survived.
        """
        lc = ctx.request_context.lifespan_context
        if not deletions:
            return {"error": "deletions list is empty"}
        try:
            sorted_ops = sorted(deletions, key=lambda x: x["start_index"], reverse=True)
            requests = [
                {
                    "deleteContentRange": {
                        "range": {
                            "startIndex": op["start_index"],
                            "endIndex": op["end_index"],
                        }
                    }
                }
                for op in sorted_ops
            ]
            with doc_invalidating(lc.doc_cache, doc_id):
                await execute_in_thread(
                    lc.docs_service.documents()
                    .batchUpdate(documentId=doc_id, body={"requests": requests})
                    .execute,
                    lc.docs_service,
                )
        except Exception as e:
            return {"error": str(e)}
        logger.debug("delete_doc_range: %d deletions in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "deletions": len(requests)}

    @tool(annotations=ToolAnnotations(title="Insert Page Break", destructiveHint=True))
    async def insert_page_break(
        doc_id: str,
        index: int,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Insert an explicit page break at a specific index in a Google Doc.

        Use get_doc_structure to find a suitable insertion index.

        Args:
            doc_id: The Google Doc file ID.
            index: Document body index where the page break should be inserted.

        Returns:
            Confirmation with docId and the insertion index.
        """
        lc = ctx.request_context.lifespan_context

        try:
            with doc_invalidating(lc.doc_cache, doc_id):
                await execute_in_thread(
                    lc.docs_service.documents()
                    .batchUpdate(
                        documentId=doc_id,
                        body={"requests": [{"insertPageBreak": {"location": {"index": index}}}]},
                    )
                    .execute,
                    lc.docs_service,
                )
        except Exception as e:
            return {"error": str(e)}

        logger.debug("insert_page_break: at index %d in doc %s", index, doc_id)
        return {"docId": doc_id, "index": index}

    @tool(annotations=ToolAnnotations(title="Insert Soft-Break Paragraph", destructiveHint=True))
    async def insert_softbreak_paragraph(
        doc_id: str,
        index: int,
        lines: list[dict],
        named_style_type: str | None = None,
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Insert a single paragraph built from multiple lines joined by soft line
        breaks (Shift+Enter in the Docs UI). The paragraph's style is left
        untouched unless a named_style_type is passed, in which case it is set
        explicitly over the whole paragraph.

        Use this for metadata/header-style blocks that must render as one tight
        paragraph with no blank line between rows — e.g. a document header block:
            Document ID: KH-OPS-001   (bold)
            Category: AWS / Database
            Source: ...
        insert_doc_text with "\\n" between lines creates separate paragraphs with a
        blank line between them instead.

        Passing a named_style_type applies the Docs API behaviour documented
        on style_doc_range: updateParagraphStyle re-applies the named style's
        own text properties over the paragraph's runs, clearing any inline
        text styles the paragraph carried. It also sidesteps
        delete_doc_range's paragraph-merge style-inheritance gotcha (see its
        docstring). To replace existing content with a soft-break block, delete
        it first with delete_doc_range, then call this tool at the same index
        passing named_style_type (e.g. NORMAL_TEXT): the deletion's merge
        leaves the position styled by the paragraph it merged into, so the
        original style cannot be assumed to have survived.

        Either way, set the styles you want on the line dicts rather than
        relying on the paragraph's previous formatting: inserted lines inherit
        the inline style of the character before index (bold, italic,
        strikethrough, link included) — except at a paragraph's first index,
        where the style comes from the character at index, the paragraph's own
        first character — and a line can set a field to false to
        clear an inherited style. A font_family line that sends no bold of its
        own keeps the bold the insert inherited: the weightedFontFamily request
        would clear it, so it is restored after, as style_doc_range does. Not
        when a named_style_type is passed, though: the paragraph-style request
        clears inherited bold over the whole paragraph first, so the inherited
        bold is neither read nor restored then.

        Args:
            doc_id: The Google Doc file ID.
            index: Document position to insert at. Use get_doc_structure to find it.
            lines: List of line dicts, each with:
                text (str): the line's text (required, non-empty).
                Optional per-line text style, applied only to that line's own span
                (same vocabulary as style_doc_range's text-style fields):
                  bold, italic, underline, strikethrough (bool)
                  font_size (float): size in points
                  font_family (str): font family name (e.g. "Courier New", "Consolas")
                  foreground_color (dict): {"red": 0-1, "green": 0-1, "blue": 0-1}
                  link_url (str | null): set a hyperlink (null to clear)
            named_style_type: Optional paragraph style applied to the whole
                paragraph the inserted block ends up in (per Docs API
                updateParagraphStyle semantics, this covers the entire paragraph
                touched by the insert, not just the newly-inserted span):
                NORMAL_TEXT, HEADING_1 … HEADING_6, TITLE, SUBTITLE.

        Returns:
            Confirmation with docId, start_index, end_index (the inserted block's
            span), and line_ranges — a parallel list of {start_index, end_index}
            per line, usable directly with style_doc_range for any styling beyond
            what this call already applied.
        """
        lc = ctx.request_context.lifespan_context

        if not lines:
            return {"error": "lines list is empty"}
        for line in lines:
            if not line.get("text"):
                return {"error": "every line must have non-empty 'text'"}
        if named_style_type is not None and named_style_type not in _NAMED_STYLE_TYPES:
            return {
                "error": f"invalid named_style_type {named_style_type!r}; must be one of: "
                f"{', '.join(sorted(_NAMED_STYLE_TYPES))}"
            }

        joined_text = "\v".join(line["text"] for line in lines)
        end_index = index + utf16_len(joined_text)

        # #1499 item 4: a font_family line that sends no bold of its own would
        # clear the direct bold the insert inherits from the character before
        # index — the same weightedFontFamily behaviour style_doc_range restores
        # after (#1273) — so read the neighbour's own bold once,
        # before the insert. Bold a run carries via its paragraph's named style
        # is not the run's and not affected by the font request, exactly as
        # _bold_runs_in_range's own docstring says, so only a directly bold
        # neighbour restores anything. At a paragraph's first index the
        # neighbour is the character at index itself — the paragraph's own
        # first character — not the one before it (#1584). Skipped entirely when
        # named_style_type is set: the updateParagraphStyle request goes out
        # first and clears the inherited bold over the whole paragraph, so a
        # restore would re-bold the font-only lines alone.
        font_only_lines = {
            i for i, line in enumerate(lines) if "font_family" in line and "bold" not in line
        }
        inherits_bold = False
        if font_only_lines and named_style_type is None:
            try:
                doc = await execute_in_thread(
                    lc.docs_service.documents().get(documentId=doc_id).execute,
                    lc.docs_service,
                )
            except Exception as e:
                return {"error": str(e)}
            # #1584: Docs styles text inserted at a paragraph's first index
            # from the character after index, not from the previous
            # paragraph's newline, so probe the neighbour the insert actually
            # inherits from.
            probe = index if _is_paragraph_start(doc, index) else index - 1
            inherits_bold = bool(_bold_runs_in_range(doc, probe, probe + 1))

        requests: list[dict[str, Any]] = [
            {"insertText": {"location": {"index": index}, "text": joined_text}},
        ]
        # #1489: only touch the paragraph's style when asked to — an unasked
        # updateParagraphStyle re-applies the named style's text properties
        # over the paragraph's runs and wipes its existing inline styles.
        if named_style_type is not None:
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": index, "endIndex": end_index},
                        "paragraphStyle": {"namedStyleType": named_style_type},
                        "fields": "namedStyleType",
                    }
                }
            )

        line_ranges: list[dict[str, int]] = []
        cursor = index
        for i, line in enumerate(lines):
            line_start = cursor
            line_end = line_start + utf16_len(line["text"])
            line_ranges.append({"start_index": line_start, "end_index": line_end})

            text_style, fields = _text_style_and_fields(line)
            # A link-clear-only line legitimately produces an empty text_style
            # with fields=["link"] — see _text_style_and_fields's own docstring
            # (#408), the single source of truth for this contract rather than
            # a second copy of the same prose (issue #448).
            if fields:
                requests.append(
                    {
                        "updateTextStyle": {
                            "range": {"startIndex": line_start, "endIndex": line_end},
                            "textStyle": text_style,
                            "fields": ",".join(fields),
                        }
                    }
                )
                # Restore the direct bold the font request clears (#1273), in
                # the same batchUpdate and after it, as style_doc_range does.
                # Only a line that sends no bold of its own is restored, only
                # when the insert inherited bold at all — and never when
                # named_style_type is set, per the skip above.
                if named_style_type is None and i in font_only_lines and inherits_bold:
                    requests.append(
                        {
                            "updateTextStyle": {
                                "range": {"startIndex": line_start, "endIndex": line_end},
                                "textStyle": {"bold": True},
                                "fields": "bold",
                            }
                        }
                    )

            cursor = line_end + (1 if i < len(lines) - 1 else 0)  # +1 for the "\v" separator

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

        logger.debug(
            "insert_softbreak_paragraph: %d lines at index %d in doc %s",
            len(lines),
            index,
            doc_id,
        )
        return {
            "docId": doc_id,
            "start_index": index,
            "end_index": end_index,
            "line_ranges": line_ranges,
        }
