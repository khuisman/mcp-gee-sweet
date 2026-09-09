import logging
from typing import Any

from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from ...auth import execute_in_thread
from .indices import utf16_len
from .style import _NAMED_STYLE_TYPES, _text_style_and_fields

logger = logging.getLogger(__name__)


def register(tool):
    @tool(annotations=ToolAnnotations(title="Insert Document Text", destructiveHint=True))
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
                    (the headerId / footerId returned by create_header / create_footer).
                    Omit to insert into the document body.

        Returns:
            Confirmation with docId and count of insertions applied.
        """
        lc = ctx.request_context.lifespan_context
        if not insertions:
            return {"error": "insertions list is empty"}
        try:
            sorted_ops = sorted(insertions, key=lambda x: x["index"], reverse=True)
            requests = []
            for op in sorted_ops:
                location: dict[str, Any] = {"index": op["index"]}
                if "segment_id" in op:
                    location["segmentId"] = op["segment_id"]
                requests.append({"insertText": {"location": location, "text": op["text"]}})
            await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": requests})
                .execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}
        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("insert_doc_text: %d insertions in doc %s", len(requests), doc_id)
        return {"docId": doc_id, "insertions": len(requests)}

    @tool(annotations=ToolAnnotations(title="Delete Document Range", destructiveHint=True))
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
            await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": requests})
                .execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}
        lc.doc_cache.mark_dirty(doc_id)
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

        lc.doc_cache.mark_dirty(doc_id)
        logger.debug("insert_page_break: at index %d in doc %s", index, doc_id)
        return {"docId": doc_id, "index": index}

    @tool(annotations=ToolAnnotations(title="Insert Soft-Break Paragraph", destructiveHint=True))
    async def insert_softbreak_paragraph(
        doc_id: str,
        index: int,
        lines: list[dict],
        named_style_type: str = "NORMAL_TEXT",
        ctx: Context = None,
    ) -> dict[str, Any]:
        """
        Insert a single paragraph built from multiple lines joined by soft line
        breaks (Shift+Enter in the Docs UI), with the paragraph's style set
        explicitly rather than inherited from whatever is at `index`.

        Use this for metadata/header-style blocks that must render as one tight
        paragraph with no blank line between rows — e.g. a document header block:
            Document ID: KH-OPS-001   (bold)
            Category: AWS / Database
            Source: ...
        insert_doc_text with "\\n" between lines creates separate paragraphs with a
        blank line between them instead. This also sidesteps delete_doc_range's
        paragraph-merge style-inheritance gotcha (see its docstring) by setting
        namedStyleType explicitly on the whole paragraph the block lands in, rather
        than leaving it to whichever neighboring paragraph it happened to merge into.

        To replace existing content with a soft-break block: delete it first with
        delete_doc_range, then call this tool at the same index.

        Args:
            doc_id: The Google Doc file ID.
            index: Document position to insert at. Use get_doc_structure to find it.
            lines: List of line dicts, each with:
                text (str): the line's text (required, non-empty).
                Optional per-line text style, applied only to that line's own span
                (same vocabulary as style_doc_range's text-style fields):
                  bold, italic, underline, strikethrough (bool)
                  font_size (float): size in points
                  foreground_color (dict): {"red": 0-1, "green": 0-1, "blue": 0-1}
                  link_url (str | null): set a hyperlink (null to clear)
            named_style_type: Paragraph style applied to the whole paragraph the
                inserted block ends up in (per Docs API updateParagraphStyle
                semantics, this covers the entire paragraph touched by the insert,
                not just the newly-inserted span). NORMAL_TEXT (default),
                HEADING_1 … HEADING_6, TITLE, SUBTITLE.

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
        if named_style_type not in _NAMED_STYLE_TYPES:
            return {
                "error": f"invalid named_style_type {named_style_type!r}; must be one of: "
                f"{', '.join(sorted(_NAMED_STYLE_TYPES))}"
            }

        joined_text = "\v".join(line["text"] for line in lines)
        end_index = index + utf16_len(joined_text)

        requests: list[dict[str, Any]] = [
            {"insertText": {"location": {"index": index}, "text": joined_text}},
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": index, "endIndex": end_index},
                    "paragraphStyle": {"namedStyleType": named_style_type},
                    "fields": "namedStyleType",
                }
            },
        ]

        line_ranges: list[dict[str, int]] = []
        cursor = index
        for i, line in enumerate(lines):
            line_start = cursor
            line_end = line_start + utf16_len(line["text"])
            line_ranges.append({"start_index": line_start, "end_index": line_end})

            text_style, fields = _text_style_and_fields(line)
            # See style_doc_range's identical comment (#408): a link-clear-only
            # line legitimately produces an empty text_style with fields=["link"].
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

            cursor = line_end + (1 if i < len(lines) - 1 else 0)  # +1 for the "\v" separator

        try:
            await execute_in_thread(
                lc.docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": requests})
                .execute,
                lc.docs_service,
            )
        except Exception as e:
            return {"error": str(e)}

        lc.doc_cache.mark_dirty(doc_id)
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
