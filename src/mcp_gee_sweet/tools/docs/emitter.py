"""Document AST → Docs API batchUpdate requests."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass, replace

from ...auth import execute_in_thread
from .ast import BulletItem, Cell, DocNode, Heading, Image, NamedBlock, Paragraph, Row, Run, Table
from .batch_retry import send_dropping_failed_images
from .indices import isolated_bullet_run_wrap_requests, utf16_len
from .md_to_html import valid_gfm_domain

logger = logging.getLogger(__name__)


class CellImages:
    """The images a table fill embeds in cells (#1073), and how it sends its batches.

    uris: id(image) -> its resolved URI, for each cell image to embed. An image with no
    entry is skipped, like an unresolved body image. A dropped image's entry is removed,
    so a nested table after it in the same cell stops counting it.

    run_batch sends one batchUpdate. failed_request_index reads the index of the
    insertInlineImage an error names (None for any other error), and on_dropped is told
    about each image dropped that way. embedded collects id(image) for every image whose
    insert went out in a batch that succeeded, updated as each batch lands, so the
    caller can tell which resolved images the fill never placed, even after a raise.
    """

    def __init__(
        self,
        uris: dict[int, str],
        run_batch: Callable[[list[dict]], Awaitable[None]],
        failed_request_index: Callable[[Exception], int | None],
        on_dropped: Callable[[Image, Exception], None],
    ):
        self.uris = uris
        self.embedded: set[int] = set()
        self._run_batch = run_batch
        self._failed_request_index = failed_request_index
        self._on_dropped = on_dropped
        # id(insert) -> (insert, image, its link request or None) for the batch being
        # built and sent. It holds the request dicts themselves and is cleared once that
        # batch settles, so no id() here can belong to a later batch's request.
        self._pending: dict[int, tuple[dict, Image, dict | None]] = {}

    def insert_requests(self, image: Image, position: int) -> list[dict]:
        """The insertInlineImage (and link request) for `image`, recorded for the retry."""
        requests = _image_insert_requests(image, self.uris[id(image)], position)
        link = requests[1] if len(requests) > 1 else None
        self._pending[id(requests[0])] = (requests[0], image, link)
        return requests

    async def execute(self, requests: list[dict]) -> None:
        """Send one cell-fill batch, dropping each image Google can't fetch
        (batch_retry.send_dropping_failed_images).

        Dropping an image never moves another request: within a cell the images go
        after its text, latest first, and cells run latest first, so every request
        after an image sits at or before it. A split cuts the batch at the failed
        image: a batchUpdate applies its requests in order, so sending L[:i] and then
        L[i:] does what sending L would. Splitting anywhere else isn't safe, since an
        earlier cell's text moves every later position; the body's split (all text,
        then the images) would misplace every image after the first cell.
        """
        try:
            await send_dropping_failed_images(
                requests,
                self._run_batch,
                self._drop,
                lambda _remaining, index: index,
                self._applied,
            )
        finally:
            self._pending.clear()

    def _applied(self, batch: list[dict]) -> None:
        sent = {id(r) for r in batch}
        self.embedded.update(
            id(image) for insert, image, _ in self._pending.values() if id(insert) in sent
        )

    def _drop(self, requests: list[dict], error: Exception) -> int | None:
        """Pop the image insert `error` names from `requests`, with its link request,
        and return the index it was at. None if `error` doesn't name one of this
        batch's image inserts."""
        index = self._failed_request_index(error)
        if index is None or index >= len(requests):
            return None
        # _pending holds its requests alive, so an id() match is the request itself.
        entry = self._pending.get(id(requests[index]))
        if entry is None:
            return None
        insert, image, link = entry
        requests.pop(index)
        if link is not None:
            requests[:] = [r for r in requests if r is not link]
        del self._pending[id(insert)]
        self.uris.pop(id(image), None)
        self._on_dropped(image, error)
        return index


@dataclass
class _PendingTable:
    """One Table node awaiting its insertTable request, plus the two bookkeeping
    values needed to place it — kept together in one list (#434 finding 5/7)
    instead of three separately-appended parallel lists (tables/table_positions/
    table_tab_offsets) indexed by a shared position, which a future edit could
    append to only one or two of without anything enforcing equal length."""

    node: Table
    position: int  # its placeholder paragraph's doc index, before tab-consumption adjustment
    tab_offset: int  # cumulative synthetic bullet-tabs consumed ahead of it by insertTable time
    order: int  # index in the top-level node list; breaks same-position ties (see below)
    rows: int  # the insertTable grid, computed once: the placeholder delete depends on it
    columns: int


def _inserted_table_length(rows: int, columns: int) -> int:
    """Indices an insertTable request adds: the newline it puts in front of the table,
    plus the table element, which spans 2 + rows * (1 + 2 * columns) (a start index,
    one per row, two per cell for the cell and its empty paragraph, and an end index).
    Confirmed live for 2x2 (13) and 2x3 (17) (#1097)."""
    return 1 + 2 + rows * (1 + 2 * columns)


@dataclass
class _SegmentMeta:
    """One non-Table node's own bookkeeping for the two loops below — a typed
    replacement for what used to be an untyped positional 5-tuple (#434 finding
    6, following the same rationale _PendingTable above already applies to the
    table bookkeeping).

    `runs` is deliberately NOT always `node.runs` — for a BulletItem whose own
    leading text had a literal tab stripped (see the main loop below, #434
    finding 1), the per-run style/position offset math further down must walk
    the *stripped* runs, not the node's original ones, or a run's own
    `utf16_len(item.text)` still counts a tab character that was never actually
    inserted — a style-range/image-position regression PR #768's QA round 2
    caught in finding 1's own first version."""

    node: DocNode
    doc_start: int
    doc_end: int
    skip_len: int
    own_tabs: int  # this node's own synthetic depth-tabs (0 unless a BulletItem)
    tabs_through: int  # synthetic depth-tabs up to and including this node's own
    runs: list[Run | Image]
    order: int  # index in the top-level node list, as _PendingTable.order


def _after_bullet_pass(position: int, tabs_before: int) -> int:
    """Map a doc index in the freshly inserted text to where it sits once the whole
    bullet pass has run. Every createParagraphBullets call removes its paragraphs'
    synthetic depth-tabs, so the index moves back by `tabs_before`: the number of
    those tabs that sat ahead of it. The one place this mapping lives, for every
    request ordered after the bullet pass (table/image inserts, quoted-bullet
    styling)."""
    return position - tabs_before


@dataclass(eq=False)
class _BulletList:
    """One Docs list: the BulletItems one createParagraphBullets call bullets, as
    segment_meta indices. A top-level list's `first`..`last` also spans every item
    nested inside it, of either type (#1072), so its one call consumes every item's
    phase-1 tabs, a trailing nested list's included (PR #1295 QA round 1).

    A list at the top of its contiguous block of items holds, in `nested`, every list
    nested anywhere inside it that isn't merged into it, in document order, so a list
    always comes before the lists nested in it. Such a nested list is usually of the
    other type, but not always: a same-type list that follows another sublist under
    the same item (ordered, bullet, ordered) is one too, so it restarts.

    `source_path` is the BulletItem.list_path of the item that started it."""

    ordered: bool
    first: int
    last: int
    min_depth: int
    source_path: tuple[int, ...]
    top: _BulletList | None  # the top-level list this one is nested in
    nested: list[_BulletList]  # top-level lists only


@dataclass
class _OpenList:
    """A list level that's still open while _bullet_lists walks the items: its depth,
    its list, the id of the source list its items come from (the last entry of their
    BulletItem.list_path; None when unknown), and whether its current item already
    has a list nested in it."""

    depth: int
    bullet_list: _BulletList
    list_id: int | None
    had_child: bool = False


def _encloses(open_list: _OpenList, node: BulletItem) -> bool:
    """Whether `node` sits in `open_list`'s source list or in a list nested in it
    (#1241). True when either side's ids are unknown, which leaves depth and type to
    decide, as before."""
    return open_list.list_id is None or not node.list_path or open_list.list_id in node.list_path


def _rejoins_root(root: _BulletList, node: BulletItem) -> bool:
    """Whether `node`, shallower than every open list, joins the block's first list:
    a run whose parents were dropped (#714) followed by more of an enclosing list. With
    ids known, only a list enclosing the root's first item qualifies, so a separate
    list after a deeper one starts its own (#1241)."""
    if root.ordered != node.ordered:
        return False
    if not root.source_path or not node.list_path:
        return True
    path = node.list_path
    return len(path) < len(root.source_path) and root.source_path[: len(path)] == path


def _bullet_lists(segment_meta: list[_SegmentMeta]) -> list[_BulletList]:
    """Group the BulletItems in `segment_meta` into Docs lists and return the
    top-level ones, in document order, each holding the lists nested in it.

    A list of the other type nested in a list stays its own Docs list, at every level
    (#1072). An item continues the open list at its depth when it comes from the same
    source list. An open list that doesn't enclose the item (`_encloses`) is closed
    first, so a different list at that depth starts a new list, and so does a
    shallower item with no open list left. A nested list joins its parent's list when
    it has the same type and is the first list nested in that parent item, which
    keeps numbered-in-numbered one Docs list as before; a later one under the same
    item is a list of its own, so it restarts. A run of contiguous items whose
    parents were dropped (#714), shallower than the block's first list, joins that
    list when it comes from a list enclosing it (`_rejoins_root`).

    Two adjacent same-type lists (`1.` then `1)` markers, or `-` then `*`) stay two
    Docs lists, at any depth, since each item carries its source lists' ids (#1241).
    The later one is a new top-level list, or a nested list that restarts. Items with
    no ids (an AST not built by html_parser) group by depth and type alone, as before.

    A non-BulletItem segment ends the block. A Table isn't in segment_meta, so a table
    between two items keeps them in one list, as before."""
    tops: list[_BulletList] = []
    stack: list[_OpenList] = []
    root: _BulletList | None = None
    for i, seg in enumerate(segment_meta):
        node = seg.node
        if not isinstance(node, BulletItem):
            stack, root = [], None
            continue
        depth, ordered = node.depth, node.ordered
        while stack and (stack[-1].depth > depth or not _encloses(stack[-1], node)):
            stack.pop()
        if stack and stack[-1].depth == depth:
            if stack[-1].bullet_list.ordered == ordered:
                bullet_list = stack[-1].bullet_list
                bullet_list.last = i
                (bullet_list.top or bullet_list).last = i
                stack[-1].had_child = False
                continue
            stack.pop()
        if stack:
            enclosing = stack[-1]
            if enclosing.bullet_list.ordered == ordered and not enclosing.had_child:
                bullet_list = enclosing.bullet_list
            else:
                top = enclosing.bullet_list.top or enclosing.bullet_list
                bullet_list = _BulletList(ordered, i, i, depth, node.list_path, top=top, nested=[])
                top.nested.append(bullet_list)
            enclosing.had_child = True
        elif root is not None and _rejoins_root(root, node):
            bullet_list = root
        else:
            bullet_list = root = _BulletList(
                ordered, i, i, depth, node.list_path, top=None, nested=[]
            )
            tops.append(bullet_list)
        bullet_list.last = i
        (bullet_list.top or bullet_list).last = i
        bullet_list.min_depth = min(bullet_list.min_depth, depth)
        list_id = node.list_path[-1] if node.list_path else None
        stack.append(_OpenList(depth, bullet_list, list_id))
    return tops


def _bullet_preset(ordered: bool) -> str:
    return "NUMBERED_DECIMAL_ALPHA_ROMAN" if ordered else "BULLET_DISC_CIRCLE_SQUARE"


def _top_list_requests(top: _BulletList, segment_meta: list[_SegmentMeta]) -> list[dict]:
    """The bullet requests for one top-level list and every list nested in it (#1072).

    One createParagraphBullets call over `top`'s whole range puts every item in it,
    nested lists included, into one list at its tab-encoded level. A Docs list has a
    single preset and numbers each level by listId, so the items of `top` (and of a
    same-type list merged into it) keep counting past a nested list, even though that
    list sits inside the range. Then each list in `top.nested`, parent before child,
    is taken back out (confirmed live, #1072), whatever its type: its bullets are deleted,
    its indent zeroed (deleteParagraphBullets leaves the level's indent, which the next
    createParagraphBullets would read as extra depth, #1069), its items' depth-tabs
    inserted again (the first call consumed them), and the range bulleted with its
    own preset through the anchor wrap, since its items all sit at depth > 0. The
    paragraph just before a nested list is always listed by then, and Docs would join
    the range to that paragraph's list when the presets match (a restarted same-type
    sublist, #1241), so the wrap puts a barrier paragraph between them. A
    nested list's range contains the lists nested in it, which the later ones take
    back out in turn. The listId left behind on a paragraph is the list it belongs to.

    Every nested list's tabs are inserted and consumed again, so the whole sequence
    removes each item's tabs once, as a single call would: _after_bullet_pass holds.
    Positions after the first call are in `top`'s own coordinates, with its tabs gone;
    nothing before `top` has shifted yet (the lists are applied latest-first)."""
    start = segment_meta[top.first].doc_start
    end = segment_meta[top.last].doc_end
    preset = _bullet_preset(top.ordered)
    if top.min_depth == 0:
        requests: list[dict] = [
            {
                "createParagraphBullets": {
                    "range": {"startIndex": start, "endIndex": end},
                    "bulletPreset": preset,
                }
            }
        ]
    else:
        # Isolated list: every item sits at depth > 0 with no depth-0 sibling in this
        # same call to anchor nesting level 0. createParagraphBullets assigns each
        # paragraph nestingLevel = (its leading-tab count) - (the minimum leading-tab
        # count across the whole range), so a list with no 0-tab paragraph collapses
        # entirely to nestingLevel 0 — rendering the depth-0 glyph (● disc) even though
        # the per-level indent is bumped so the item still *looks* nested (confirmed
        # live, #439). isolated_bullet_run_wrap_requests (indices.py, shared with
        # style.py per #727) prepends a throwaway 0-tab anchor paragraph, bullets the
        # extended range (anchor -> level 0, real items -> their true level and its
        # correct glyph), then deletes the anchor. The insert (+1) and delete (-1)
        # cancel, so every position outside [start, end] — later lists, table/image
        # inserts — is left exactly where an ordinary single call would leave it.
        #
        # Because the anchor always contributes 0 tabs, the minimum across the
        # extended range is always 0 regardless of min_depth — so every item lands at
        # nestingLevel == its own depth exactly (min_depth == 1 -> level 1,
        # min_depth == 2 -> level 2, etc.), never clamped to level 1. This is a
        # deliberate decision (#714, following the #439 fix in PR #711): the converter
        # renders the source's true nesting depth faithfully rather than clamping a
        # deeply-nested fragment (whose ancestors were dropped for having no text of
        # their own) to look one level deep.
        requests = isolated_bullet_run_wrap_requests(start, end, preset)

    tabs_ahead = segment_meta[top.first].tabs_through - segment_meta[top.first].own_tabs

    def after_top(index: int) -> tuple[int, int]:
        """Segment `index`'s (start, end) once `top`'s first call consumed its tabs."""
        seg = segment_meta[index]
        own_start = seg.tabs_through - seg.own_tabs - tabs_ahead
        return seg.doc_start - own_start, seg.doc_end - (seg.tabs_through - tabs_ahead)

    for bullet_list in top.nested:
        list_start = after_top(bullet_list.first)[0]
        list_end = after_top(bullet_list.last)[1]
        rng = {"startIndex": list_start, "endIndex": list_end}
        requests.append({"deleteParagraphBullets": {"range": rng}})
        requests.append(
            {
                "updateParagraphStyle": {
                    "range": rng,
                    "paragraphStyle": {
                        "indentStart": {"magnitude": 0, "unit": "PT"},
                        "indentFirstLine": {"magnitude": 0, "unit": "PT"},
                    },
                    "fields": "indentStart,indentFirstLine",
                }
            }
        )
        tabs = 0
        for index in range(bullet_list.last, bullet_list.first - 1, -1):
            # Every item here sits deeper than the list it's nested in, so it has tabs.
            own_tabs = segment_meta[index].own_tabs
            requests.append(
                {
                    "insertText": {
                        "location": {"index": after_top(index)[0]},
                        "text": "\t" * own_tabs,
                    }
                }
            )
            tabs += own_tabs
        requests.extend(
            isolated_bullet_run_wrap_requests(
                list_start, list_end + tabs, _bullet_preset(bullet_list.ordered), barrier=True
            )
        )
    return requests


def _strip_bullet_leading_tabs(runs: list[Run | Image]) -> list[Run | Image]:
    """Return `runs` with literal leading tab character(s) removed from the
    start of its own text, without mutating the caller's Run/Image objects —
    the AST is caller-owned and this function must stay side-effect-free on it
    (contrast html_parser.py's `_make_bullet_item`, which mutates in place, but
    only ever on a list it just built from its own fresh buffer, never on an
    already-finalized AST a caller still holds a reference to).

    A run that becomes empty after stripping is dropped entirely — mirrors
    `_make_bullet_item`'s own `runs.pop(0)` after its checkbox-marker strip —
    so a leading tab spanning more than one run (e.g. a tab-only run followed
    by a run whose own text also starts with a tab) is still fully consumed.
    Stops at the first run with any remaining text; an Image in between
    contributes no text and can't itself carry a leading tab, so it's passed
    through unchanged without stopping the scan.
    """
    result: list[Run | Image] = []
    for i, item in enumerate(runs):
        if not isinstance(item, Run):
            result.append(item)
            continue
        new_text = item.text.lstrip("\t")
        if not new_text:
            continue  # fully consumed — drop and keep scanning
        if new_text != item.text:
            item = replace(item, text=new_text)
        result.append(item)
        result.extend(runs[i + 1 :])
        break
    return result


def _is_code_paragraph(node: DocNode) -> bool:
    """A Paragraph whose every Run is code-styled (font_family='Courier New') is
    the AST shape html_parser.py builds for a <pre><code> block (#103) — mirrors
    ast_to_markdown.py's identical _is_code_block predicate, kept as a separate
    copy rather than a shared import to avoid a write/read circular import
    between this module and ast_to_markdown.py (which already imports from here)."""
    if not isinstance(node, Paragraph):
        return False
    runs = [r for r in node.runs if isinstance(r, Run)]
    return bool(runs) and all(r.font_family == "Courier New" for r in runs)


def extract_images(nodes: list[DocNode]) -> list[Image]:
    """Collect every Image node in `nodes`, in document order.

    Used by the caller (docs/content.py, an async function) to resolve each
    image's src to a fetchable URI — a Drive upload, a share-permission
    grant, or both — *before* calling ast_to_requests, since that stays a
    synchronous, I/O-free function like the rest of this module (#333).

    Walks body-level nodes' own `runs` and every table cell's children, recursing
    into nested tables (#1073).
    """
    images: list[Image] = []
    for node in nodes:
        items = iter_cell_leaves(node) if isinstance(node, Table) else node.runs
        images.extend(item for item in items if isinstance(item, Image))
    return images


def unstorable_link_urls(nodes: list[DocNode]) -> list[str]:
    """Every distinct link target in `nodes` that _storable_link_url refuses, in
    document order: the links ast_to_requests and fill_tables will write as plain
    text (#1180). Walks the same leaves as extract_images, so a linked image and a
    table cell's runs count too. Each target is the stripped value _storable_link_url
    judged, so " ./guide.md" and "./guide.md" are one target. An empty or
    whitespace-only target names nothing to report and is skipped."""
    dropped: dict[str, None] = {}
    for node in nodes:
        items = iter_cell_leaves(node) if isinstance(node, Table) else node.runs
        for item in items:
            target = (item.link_url or "").strip()
            if target and _storable_link_url(target) is None:
                dropped[target] = None
    return list(dropped)


def iter_cell_leaves(table: Table) -> Iterator[Run | Image]:
    """Every Run and Image in `table`'s cells, nested tables included, in document order."""
    for row in table.rows:
        for cell in row.cells:
            for child in cell.children:
                if isinstance(child, Table):
                    yield from iter_cell_leaves(child)
                else:
                    yield child


def ast_to_requests(
    nodes: list[DocNode],
    start_index: int = 1,
    image_uris: dict[int, str] | None = None,
    *,
    image_links: dict[int, dict] | None = None,
) -> tuple[list[dict], list[Table]]:
    """Convert AST nodes to phase-1 batchUpdate requests and a list of Table nodes.

    Requests are built in three ordering-sensitive stages, applied in this order:

      1. Styling requests (paragraph/heading/NamedBlock styles, blockquote styling,
         inline run styles) — these assume no position has shifted yet, since every
         index they reference was computed against the freshly-built full_text before
         any other request has run.
      2. createParagraphBullets calls for BulletItem nesting (#336) — one call per
         top-level list, followed by the requests that take each nested list not
         merged into it back out (#1072), applied in descending document order
         (see the grouping loop below). Each call consumes/removes its own
         leading tab characters, shifting every later position backward, so this
         stage must run after stage 1 (which assumes nothing has shifted) but before
         stage 3 (whose own positions are pre-adjusted for exactly this shift).
      3. A combined descending-position pass for insertTable + insertInlineImage
         requests (#333) — both shift later positions the same way stage 2 does, so
         they're interleaved by true final position rather than processed as two
         separate blocks.

    Tables are NOT filled here. The caller must execute a second pass using fill_tables()
    after running the phase-1 batchUpdate, so that live cell indices are available.

    image_uris: maps id(image) (for each Image returned by extract_images(nodes), called
    on this same `nodes` value beforehand) to its already-resolved fetchable URI. An Image
    with no entry here (never resolved, or resolution failed) is silently omitted from the
    requests — same fallback as any other unsupported construct — since the Docs API's
    insertInlineImage has no notion of "insert later"; the caller is expected to have
    already recorded why that image failed via extract_images's own resolution pass.

    image_links: if given, filled with id(insertInlineImage request) -> the
    updateTextStyle request that links that image (#977), so a caller that drops a
    failed image request can drop its link request too, by identity rather than by
    matching request shapes.

    Returns (requests, tables) where tables is the list of Table AST nodes in document
    order.
    """
    if image_uris is None:
        image_uris = {}
    nodes, separators = _with_quote_separators(nodes)
    text_parts: list[str] = []
    utf16_offset = 0
    segment_meta: list[_SegmentMeta] = []
    # Nested-bullet leading tabs (see below) are consumed/removed by their own
    # createParagraphBullets call, shifting everything after them backward — including
    # any table (or image — #333) positioned later in the doc. pending_tables tracks,
    # for each table, how many such tabs will have been consumed ahead of it by the
    # time insertTable actually runs; segment_meta's own tabs_through field does the
    # same for images (see below).
    pending_tables: list[_PendingTable] = []
    cumulative_tabs = 0

    for order, node in enumerate(nodes):
        if isinstance(node, Table):
            num_rows = len(node.rows)
            num_cols = max((sum(c.colspan for c in row.cells) for row in node.rows), default=0)
            if num_rows == 0 or num_cols == 0:
                # No insertTable request is emitted below for a degenerate table, so it must
                # not be added to pending_tables either — fill_tables() zips the returned
                # tables list positionally against the tables actually present in the live
                # doc, and a table with no insertTable request never shows up there.
                continue
            pending_tables.append(
                _PendingTable(
                    node, start_index + utf16_offset, cumulative_tabs, order, num_rows, num_cols
                )
            )
            # A placeholder paragraph to insert the table at, deleted right after it
            # (#1097). insertTable gives the table and its empty cells the style at the
            # insertion point: inserted at the next block, a list or quote indented the
            # table (an indent the API can't reset afterward) and that block's first
            # character's text style (bold, Courier New, a heading's color) went into
            # every cell. The placeholder is reset to plain after the bullet pass (below),
            # so the table starts plain.
            text_parts.append("\n")
            utf16_offset += 1
        else:
            doc_start = start_index + utf16_offset
            # Leading tab characters encode a bullet's nesting depth for
            # createParagraphBullets, which infers (and removes) nesting level from
            # leading tabs in each paragraph — the only mechanism the Docs API exposes
            # for setting it (#336). Consumed later by the nested-bullet pass below.
            # node.depth is never negative — html_parser.py's _make_bullet_item clamps
            # an orphan <li>'s (outside any <ul>/<ol>) depth to 0 at the source, so it
            # takes the same direct min_depth==0 path a normal depth-0 item does below
            # rather than needlessly falling into the isolated-run wrap path (#434
            # finding 3). Clamping there once, instead of at every consumer here,
            # closes finding 4 (the clamp used to be repeated 3x in this file alone).
            tabs = "\t" * node.depth if isinstance(node, BulletItem) else ""
            # Checkbox glyph prefix for task list items
            prefix = ""
            if isinstance(node, BulletItem) and node.checked is not None:
                prefix = "☑ " if node.checked else "☐ "
            # Images (#333) contribute zero characters here — they're not part of the
            # text at all, just a positional marker resolved into its own
            # insertInlineImage request below, exactly like a Table.
            offset_runs = node.runs
            run_text = "".join(r.text for r in node.runs if isinstance(r, Run))
            if isinstance(node, BulletItem) and run_text.startswith("\t"):
                # A literal leading tab in the item's own source text (e.g.
                # hand-formatted HTML/markdown) is indistinguishable, once
                # concatenated with `tabs` above, from our own synthesized
                # depth-tabs — createParagraphBullets reads *all* leading tab
                # characters in the paragraph to infer nesting level, not just the
                # ones this function intended as depth markers. Left un-stripped,
                # it would nest the item one level deeper than intended AND get
                # consumed/removed by that same call without being counted in
                # cumulative_tabs, desyncing every later table/image position
                # (#434 finding 1). Stripped instead of preserved, since the
                # alternative silently corrupts nesting depth for the whole item.
                # Applies unconditionally, at every depth including 0 — even with
                # no synthetic tabs of our own to merge with, a lone literal
                # leading tab is still misread by createParagraphBullets as a
                # depth-1 signal relative to the rest of the run's own call. This
                # IS a real content-loss tradeoff at depth 0 specifically: a
                # genuinely-authored leading tab character (as opposed to one a
                # hand-formatted source merely used for indentation) is silently
                # dropped rather than preserved and escaped some other way — no
                # visual placeholder is substituted for it. Accepted as the
                # simpler behavior (#434 finding 5, QA round 2) since the Docs API
                # gives this function no way to insert a literal leading tab
                # character into a bulleted paragraph without it being reread as
                # a nesting-depth signal on the very next createParagraphBullets
                # call regardless of what emitted it.
                #
                # offset_runs (used below by the per-run style/position offset
                # math, segment_meta.runs) must reflect this exact same strip —
                # node.runs itself is left untouched (this function must not
                # mutate the caller's AST), so a style range or image position
                # computed from node.runs's own unstripped run.text would still
                # count the removed tab character(s), overrunning by however many
                # were stripped — PR #768's QA round 2 caught this in finding 1's
                # own first version.
                offset_runs = _strip_bullet_leading_tabs(node.runs)
                run_text = "".join(r.text for r in offset_runs if isinstance(r, Run))
            text = prefix + run_text
            # A multi-line fenced code block is one Paragraph node whose Run text
            # carries embedded "\n" line breaks (html_parser.py's <pre> handling) —
            # but the Docs API treats every "\n" in inserted text as a new paragraph
            # boundary, so inserting it literally here silently fragments one code
            # block into N separate NORMAL_TEXT paragraphs (issue #719), contradicting
            # markdown-support.md's own documented mapping of a fenced block to a
            # single "monospace paragraph". Using "\v" (the same soft-line-break
            # convention insert_softbreak_paragraph already uses) for the *embedded*
            # breaks keeps the whole block as one Docs paragraph while still
            # rendering each line on its own visual line; the node's own trailing
            # "\n" appended below is untouched, since that one is a real paragraph
            # boundary to whatever node comes next. doc_to_ast.py's _text_run_to_run
            # reverses this on read, so get_doc_as_markdown round-trips it correctly.
            if _is_code_paragraph(node) and "\n" in text:
                text = text.replace("\n", "\v")
            # Every node reaching this loop is one html_parser.py already decided
            # is worth a line in the doc — a node with runs=[] (an unsupported
            # construct like a bare <hr>, #401) as much as a node whose runs are
            # non-empty but whitespace-only (e.g. a standalone `&nbsp;` used as a
            # deliberate blank-line spacer, #402). Emit its text as-is rather than
            # re-deciding "is this content" here; the empty-string case (runs=[])
            # still contributes just the trailing "\n" below.
            appended_text = tabs + text + "\n"
            text_parts.append(appended_text)
            utf16_offset += utf16_len(appended_text)
            doc_end = start_index + utf16_offset
            if tabs:
                cumulative_tabs += utf16_len(tabs)
            # Captured *after* this node's own tabs are added: any image inside this
            # node's own runs sits past those tabs (skip_len already accounts for
            # them), so its own createParagraphBullets removal — part of the same
            # descending pass images and tables share below — shifts it too, not
            # just tabs from strictly earlier nodes.
            segment_meta.append(
                _SegmentMeta(
                    node=node,
                    doc_start=doc_start,
                    doc_end=doc_end,
                    skip_len=utf16_len(tabs) + utf16_len(prefix),
                    own_tabs=utf16_len(tabs),
                    tabs_through=cumulative_tabs,
                    runs=offset_runs,
                    order=order,
                )
            )

    requests: list[dict] = []
    full_text = "".join(text_parts)
    # createParagraphBullets calls are deferred: they must run after every other request
    # below (which all assume no positions have shifted yet) but before the combined
    # table/image insertion pass further down — see the loop after segment_meta for why
    # they're applied in descending document order. Each entry's value is a list because
    # an isolated depth>0 list (no depth-0 anchor item) expands to three requests — a
    # throwaway anchor insert, the bullets call, and the anchor delete — and a nested
    # list taken back out adds its own (#1072); see _top_list_requests.
    bullet_run_requests: list[tuple[int, list[dict]]] = []
    # Combined descending-position insertion pass (tables + images, #333): both shift
    # every later, not-yet-processed position, so they must be interleaved by their true
    # final position rather than processed as two separate blocks — see ast_to_requests's
    # docstring. Each entry is (sort_key, requests): an insert request, followed for a
    # linked image by the updateTextStyle that links it (#977). sort_key is
    # (final_position, node order, item order) — see the sort at the end.
    positional_inserts: list[tuple[tuple[int, int, int], list[dict]]] = []

    if full_text:
        requests.append({"insertText": {"location": {"index": start_index}, "text": full_text}})

        spacing = _block_spacing(nodes, separators)
        for seg in segment_meta:
            node = seg.node
            doc_start, doc_end = seg.doc_start, seg.doc_end
            rng = {"startIndex": doc_start, "endIndex": doc_end}

            if isinstance(node, Heading):
                requests.append(
                    {
                        "updateParagraphStyle": {
                            "range": rng,
                            "paragraphStyle": {"namedStyleType": f"HEADING_{node.level}"},
                            "fields": "namedStyleType",
                        }
                    }
                )
                requests.append({"deleteParagraphBullets": {"range": rng}})
            elif isinstance(node, Paragraph):
                requests.append({"deleteParagraphBullets": {"range": rng}})
            elif isinstance(node, NamedBlock):
                requests.append(
                    {
                        "updateParagraphStyle": {
                            "range": rng,
                            "paragraphStyle": {"namedStyleType": node.style_type},
                            "fields": "namedStyleType",
                        }
                    }
                )
                requests.append({"deleteParagraphBullets": {"range": rng}})
            # BulletItem's own createParagraphBullets request is handled by the grouping
            # pass below, not here.

            # Blockquote styling (#476): a left border + scaled indent, applied uniformly
            # regardless of node type (Heading/Paragraph/NamedBlock/BulletItem can all be
            # blockquote content) since Google Docs has no native blockquote paragraph
            # style to set instead — see docs/design/blockquote-representation.md.
            # A BulletItem's waits until after the bullet pass below:
            # createParagraphBullets overwrites both paragraph indents with the list
            # preset's own, so a quote indent set here was lost (#1056).
            if node.blockquote_depth > 0 and not isinstance(node, BulletItem):
                requests.append(_blockquote_style_request(rng, node.blockquote_depth))

            # Block spacing and quote separators (#1098). A BulletItem's spacing waits for
            # the bullet pass, like its quote styling above.
            if id(node) in separators:
                requests.extend(_collapse_paragraph_requests(rng))
            elif seg.order in spacing and not isinstance(node, BulletItem):
                requests.extend(_spacing_requests(rng, *spacing[seg.order]))

            # Inline run styles for non-table content (bold, italic, links, font_family, etc.)
            # skip_len skips past any leading nesting tabs and checkbox glyph so run
            # offsets stay accurate. Image entries (#333) contribute 0 to offset (they're
            # not part of the text) and are queued into positional_inserts instead of a
            # style request. Walks seg.runs, NOT node.runs — for a BulletItem with a
            # stripped literal leading tab (#434 finding 1), those differ, and using
            # node.runs's own unstripped text here would overrun every offset by however
            # many tab characters were stripped but never actually inserted (the
            # regression PR #768's QA round 2 caught in finding 1's own first version).
            offset = seg.skip_len
            for item_order, item in enumerate(seg.runs, start=1):
                if isinstance(item, Image):
                    uri = image_uris.get(id(item))
                    if uri is not None:
                        image_position = _after_bullet_pass(doc_start + offset, seg.tabs_through)
                        image_requests = _image_insert_requests(item, uri, image_position)
                        if image_links is not None and len(image_requests) == 2:
                            image_links[id(image_requests[0])] = image_requests[1]
                        positional_inserts.append(
                            ((image_position, seg.order, item_order), image_requests)
                        )
                    continue
                run_len = utf16_len(item.text)
                if run_len > 0:
                    style_reqs = _run_style_requests(
                        item, doc_start + offset, doc_start + offset + run_len
                    )
                    requests.extend(style_reqs)
                offset += run_len

        # One createParagraphBullets call per top-level list, rather than one call per
        # paragraph. createParagraphBullets infers nesting level from each paragraph's
        # own leading tab count, but only reliably does so *relative to the other
        # paragraphs covered by the same call* — issuing one call per paragraph let call
        # order/adjacency to an already-bulleted neighbor override the tab-encoded depth,
        # producing visibly inconsistent nesting live even though each call's own
        # leading-tab count and range boundaries were individually correct (confirmed
        # live, PR #432 QA round 1: same-depth siblings landed at different indentation
        # levels, and ordered lists lost continuous numbering). One atomic call spanning
        # the whole list is the pattern Google's own Docs API samples use for building
        # nested lists. Each list nested in it that isn't merged into it is taken back
        # out afterward, so the outer list keeps counting past it (#1072,
        # _top_list_requests).
        for top in _bullet_lists(segment_meta):
            bullet_run_requests.append(
                (segment_meta[top.first].doc_start, _top_list_requests(top, segment_meta))
            )

        # Applied latest-in-document-first: each call's own range is still valid at the
        # point it runs (nothing before it in the doc has shifted yet), and processing
        # this way means an earlier, not-yet-processed run's range is never invalidated
        # by a later run's own tab consumption (or, for an isolated run, its net-zero
        # anchor insert/delete pair).
        for _, grouped in sorted(bullet_run_requests, key=lambda item: item[0], reverse=True):
            requests.extend(grouped)

        # Blockquote styling for quoted list items (#1056) runs after the whole bullet
        # pass: createParagraphBullets overwrites both paragraph indents. Every tab has
        # been consumed by then, so ranges map through _after_bullet_pass like the
        # table/image inserts below; paragraph styling shifts nothing for them.
        for seg in segment_meta:
            if isinstance(seg.node, BulletItem) and seg.node.blockquote_depth > 0:
                rng = {
                    "startIndex": _after_bullet_pass(
                        seg.doc_start, seg.tabs_through - seg.own_tabs
                    ),
                    "endIndex": _after_bullet_pass(seg.doc_end, seg.tabs_through),
                }
                requests.append(
                    _blockquote_style_request(
                        rng, seg.node.blockquote_depth, list_level=seg.node.depth
                    )
                )
                if seg.order in spacing:
                    requests.extend(_spacing_requests(rng, *spacing[seg.order]))

        # Each table's placeholder, reset to plain after the bullet pass, since a table
        # between two same-preset list items sits inside their one createParagraphBullets
        # range (the run skips Table nodes, so both items stay one list). Mapped through
        # _after_bullet_pass like the inserts below.
        for pending in pending_tables:
            position = _after_bullet_pass(pending.position, pending.tab_offset)
            requests.extend(_table_placeholder_requests(position, pending.node.blockquote_depth))

    # Queue each table's insertTable request into the same positional_inserts pass
    # images use above. Position is adjusted for any nested-bullet leading tabs already
    # consumed ahead of it (those requests precede this combined pass in the array, so by
    # the time it runs, that many characters have already been removed from in front of
    # this table).
    #
    # The table goes in at its placeholder, which insertTable pushes to just after the
    # table; the deleteContentRange right after removes it. Everything later in the doc
    # was inserted earlier in this descending pass, so the delete shifts nothing still
    # to come. content.py's _positional_insert_tail_start counts the delete as part of
    # this pass by its position right after an insertTable.
    for pending in pending_tables:
        num_rows, num_cols = pending.rows, pending.columns
        position = _after_bullet_pass(pending.position, pending.tab_offset)
        placeholder_after = position + _inserted_table_length(num_rows, num_cols)
        positional_inserts.append(
            (
                (position, pending.order, 0),
                [
                    {
                        "insertTable": {
                            "rows": num_rows,
                            "columns": num_cols,
                            "location": {"index": position},
                        }
                    },
                    {
                        "deleteContentRange": {
                            "range": {
                                "startIndex": placeholder_after,
                                "endIndex": placeholder_after + 1,
                            }
                        }
                    },
                ],
            )
        )

    # Applied latest-document-position-first (tables and images interleaved by their true
    # final position, not as two separate blocks): each insertion's own target position is
    # still valid at the point it runs, since nothing before it in the doc has shifted yet,
    # and processing this way means an earlier, not-yet-processed insertion's position is
    # never invalidated by a later one's own content (#333 generalizes this from the
    # table-only version of the same pattern).
    #
    # Inserts that share a position (adjacent images with no text between them, or a
    # table and the image right after it) are each inserted *in front of* whatever is
    # already at that position, so the later one in the document must go first. The
    # node/item order in the key does that; sorting by position alone kept source order
    # within a tie and wrote adjacent images reversed (PR #992 QA round 1).
    for _, insert_requests in sorted(positional_inserts, key=lambda item: item[0], reverse=True):
        requests.extend(insert_requests)

    return requests, [pending.node for pending in pending_tables]


# Left-border quote bar + per-level indent (#476). Confirmed live (scratch doc round
# trip) that paragraphStyle.borderLeft is genuinely writable via updateParagraphStyle
# and persists — not one of the Docs API's read-only-despite-schema-silence fields (see
# CLAUDE.md's "Verify a ticket's API premise live" note; #404's tabStops was the
# cautionary case this now double-checks against).
_BLOCKQUOTE_INDENT_PT_PER_LEVEL = 36
_BLOCKQUOTE_BORDER = {
    "color": {"color": {"rgbColor": {"red": 0.6, "green": 0.6, "blue": 0.6}}},
    "width": {"magnitude": 3, "unit": "PT"},
    "padding": {"magnitude": 8, "unit": "PT"},
    "dashStyle": "SOLID",
}


# Paragraph indents createParagraphBullets gives a list item at nesting level n, for
# both presets ast_to_requests uses (confirmed live, #1056): first line (glyph) at
# 18 + 36n pt, wrapped text at 36 + 36n pt. Docs caps nestingLevel at 8: an item
# with more leading tabs lands at level 8 (confirmed live, PR #1089 QA round 1).
_LIST_INDENT_PT_PER_LEVEL = 36
_LIST_INDENT_START_PT = 36
_LIST_INDENT_FIRST_LINE_PT = 18
_MAX_LIST_NESTING_LEVEL = 8


def list_level_indents(level: int) -> tuple[int, int]:
    """(indentFirstLine, indentStart), in points, of a list item at nesting level
    `level` in the presets ast_to_requests uses, with `level` capped as Docs caps it."""
    level_indent = _LIST_INDENT_PT_PER_LEVEL * min(level, _MAX_LIST_NESTING_LEVEL)
    return _LIST_INDENT_FIRST_LINE_PT + level_indent, _LIST_INDENT_START_PT + level_indent


def _blockquote_style_request(rng: dict, depth: int, list_level: int | None = None) -> dict:
    """updateParagraphStyle request giving a blockquote paragraph a left border and an
    indent scaled by nesting depth — Google Docs has no native blockquote paragraph
    style, so this is the closest visual equivalent the API's ParagraphStyle exposes.

    Both indents are set: indentFirstLine is absolute, not relative to indentStart, so
    leaving it unset put a single-line quote's only line at the margin (#1056). A list
    item (`list_level` given) keeps its glyph's hanging indent, shifted by the quote
    indent; the request must run after the item's createParagraphBullets."""
    quote_indent = _BLOCKQUOTE_INDENT_PT_PER_LEVEL * depth
    first_line, start = list_level_indents(list_level) if list_level is not None else (0, 0)
    first_line += quote_indent
    start += quote_indent
    return {
        "updateParagraphStyle": {
            "range": rng,
            "paragraphStyle": {
                "indentStart": {"magnitude": start, "unit": "PT"},
                "indentFirstLine": {"magnitude": first_line, "unit": "PT"},
                "borderLeft": _BLOCKQUOTE_BORDER,
            },
            "fields": "indentStart,indentFirstLine,borderLeft",
        }
    }


# Space above and below a code block, and around a quote where it meets other content
# (#1098). Docs' NORMAL_TEXT has none, so without it a quote or code block touched the
# paragraphs around it and two code blocks in a row read as one.
_BLOCK_SPACING_PT = 8


def _quoted(node: DocNode) -> bool:
    return not isinstance(node, Table) and node.blockquote_depth > 0


def _has_named_spacing(node: DocNode) -> bool:
    """Whether the emitter gives `node` a named style with spacing of its own."""
    if isinstance(node, Heading):
        return True
    return isinstance(node, NamedBlock) and node.style_type != "NORMAL_TEXT"


def _with_quote_separators(nodes: list[DocNode]) -> tuple[list[DocNode], set[int]]:
    """Return `nodes` with an empty separator Paragraph between each two adjacent quoted
    nodes that belong to separate quotes, plus the separators' ids.

    Docs joins the left borders of adjacent paragraphs with the same border and indents
    into one bar, whatever their spacing, so two quotes in a row rendered as one (#1098).
    Only an unbordered (or differently indented) paragraph between them breaks the join,
    confirmed live; a slightly different border color or width doesn't. Two nodes are in
    one quote when one's blockquote_path is a prefix of the other's (see ast.py). The
    separator is unquoted even between two quotes nested in one outer quote: given the
    outer quote's border, its near-zero height left a stray dash of that bar (confirmed
    live), and the outer bar is already broken around the deeper-indented nested ones.
    _collapse_paragraph_requests shrinks it.
    """
    result: list[DocNode] = []
    separators: set[int] = set()
    prev: DocNode | None = None
    for node in nodes:
        if prev is not None and _quoted(prev) and _quoted(node):
            a, b = prev.blockquote_path, node.blockquote_path
            if a[: len(b)] != b and b[: len(a)] != a:
                separator = Paragraph(runs=[])
                result.append(separator)
                separators.add(id(separator))
        result.append(node)
        prev = node
    return result, separators


def _block_spacing(nodes: list[DocNode], separators: set[int]) -> dict[int, tuple[int, int]]:
    """Map a node's index in `nodes` to the (spaceAbove, spaceBelow) it needs (#1098):
    a code block gets both, and a quoted node gets space on each side where its quote
    meets content outside it (an unquoted node, a table, or the edge). Nodes inside one
    quote get none between them, so the quote stays one block.

    A separator gets space on one side only, below the quote before it: spaced on both,
    two quotes sat twice as far apart as a quote and a paragraph (PR #1199 QA round 1).
    A Heading or a TITLE/SUBTITLE NamedBlock gets no quote-edge space: an explicit
    value would replace its named style's own spacing (HEADING_1's 20pt above, say)."""

    def outside_quote(i: int, *, count_separator: bool) -> bool:
        if i < 0 or i >= len(nodes):
            return True
        if id(nodes[i]) in separators:
            return count_separator
        return not _quoted(nodes[i])

    spacing: dict[int, tuple[int, int]] = {}
    for i, node in enumerate(nodes):
        if isinstance(node, Table) or id(node) in separators:
            continue
        above = below = 0
        if _is_code_paragraph(node):
            above = below = _BLOCK_SPACING_PT
        if _quoted(node) and not _has_named_spacing(node):
            if outside_quote(i - 1, count_separator=False):
                above = _BLOCK_SPACING_PT
            if outside_quote(i + 1, count_separator=True):
                below = _BLOCK_SPACING_PT
        if above or below:
            spacing[i] = (above, below)
    return spacing


def _spacing_requests(rng: dict, above: int, below: int) -> list[dict]:
    """spaceAbove on the first paragraph of a node's range and spaceBelow on its last.
    A node whose text holds a "\\n" becomes several Docs paragraphs (#1093); spacing the
    whole range put a gap inside it (confirmed live)."""
    start, end = rng["startIndex"], rng["endIndex"]
    requests = []
    for field, magnitude, sub_range in (
        ("spaceAbove", above, {"startIndex": start, "endIndex": start + 1}),
        ("spaceBelow", below, {"startIndex": end - 1, "endIndex": end}),
    ):
        if magnitude:
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": sub_range,
                        "paragraphStyle": {field: {"magnitude": magnitude, "unit": "PT"}},
                        "fields": field,
                    }
                }
            )
    return requests


def _collapse_paragraph_requests(rng: dict) -> list[dict]:
    """Shrink an empty paragraph to near-zero height: no spacing, 1% line spacing, 1pt
    font. Shared by the quote separators (#1098) and the blank paragraph before a
    table."""
    paragraph_style = {
        "spaceAbove": {"magnitude": 0, "unit": "PT"},
        "spaceBelow": {"magnitude": 0, "unit": "PT"},
        "lineSpacing": 1,
    }
    return [
        {
            "updateParagraphStyle": {
                "range": rng,
                "paragraphStyle": paragraph_style,
                "fields": ",".join(paragraph_style),
            }
        },
        {
            "updateTextStyle": {
                "range": rng,
                "textStyle": {"fontSize": {"magnitude": 1, "unit": "PT"}},
                "fields": "fontSize",
            }
        },
    ]


def _table_placeholder_requests(position: int, blockquote_depth: int) -> list[dict]:
    """Reset a table's placeholder paragraph (#1097) to plain before its insertTable,
    since the table takes its indent and every empty cell its text style. Plain means
    no bullet (a table between two list items sits inside their bullet range), every
    paragraph field at its default (`*`: the doc's surviving final paragraph mark can
    carry a heading's style into new content), and no text style. A table inside a
    quote keeps the quote's indent, with no border, which a table doesn't take.
    Bullets go first: deleteParagraphBullets adds indent, which the reset clears."""
    rng = {"startIndex": position, "endIndex": position + 1}
    paragraph_style: dict = {"namedStyleType": "NORMAL_TEXT"}
    if blockquote_depth > 0:
        indent = {"magnitude": _BLOCKQUOTE_INDENT_PT_PER_LEVEL * blockquote_depth, "unit": "PT"}
        paragraph_style["indentStart"] = indent
        paragraph_style["indentFirstLine"] = indent
    return [
        {"deleteParagraphBullets": {"range": rng}},
        {
            "updateParagraphStyle": {
                "range": rng,
                "paragraphStyle": paragraph_style,
                "fields": "*",
            }
        },
        {"updateTextStyle": {"range": rng, "textStyle": {}, "fields": "*"}},
    ]


def _image_insert_requests(image: Image, uri: str, position: int) -> list[dict]:
    """Build the insertInlineImage request for an already-resolved image at `position`,
    followed, for a linked image, by the updateTextStyle that links it (#977).

    Docs stores an image's link on its inlineObjectElement's own textStyle, so the link
    goes over the image's one-character range [position, position + 1). It must run
    right after this insert: the descending-position pass guarantees nothing before
    `position` has shifted yet at that point. An image never inherits a neighboring
    run's link on insert (confirmed live), so an unlinked image needs no clearing
    request. content.py's retry drops the pair together when the insert fails
    (_drop_failed_image, through ast_to_requests's image_links); otherwise the link
    would land on whatever character sits at `position`."""
    request: dict = {"insertInlineImage": {"uri": uri, "location": {"index": position}}}
    if image.width is not None or image.height is not None:
        object_size: dict = {}
        if image.width is not None:
            object_size["width"] = {"magnitude": image.width, "unit": "PT"}
        if image.height is not None:
            object_size["height"] = {"magnitude": image.height, "unit": "PT"}
        request["insertInlineImage"]["objectSize"] = object_size
    link_url = _storable_link_url(image.link_url)
    if link_url is None:
        return [request]
    return [request, _image_link_request(link_url, position)]


# RFC 3986: a scheme is case-insensitive and an open registry, so acceptance is
# structural rather than a list that drops working targets every time a new
# scheme shows up in a document.
_STORABLE_LINK_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
# A scheme-less target that still names a host gets https:// (#1180). Matched
# against the whole target, which may hold no whitespace (a dead link either way).
# Protocol-relative "//host/x": the host starts with a letter or digit, so "//",
# "///x", "//?q", "//#x", "//:80" and "//-" name none. A bare "www." host follows
# GFM's extended www autolink: "www." then a valid domain with at least one more
# ".", checked by the autolinker's own md_to_html.valid_gfm_domain, so the
# relative file "WWW.md" isn't taken for a host.
_HOST_RELATIVE_LINK = re.compile(r"//[A-Za-z0-9][A-Za-z0-9.-]*(?:[:/?#]\S*)?")
_BARE_WWW_LINK = re.compile(
    r"(www\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+)(?:[/:?#]\S*)?", re.IGNORECASE
)


def _storable_link_url(link_url: str | None) -> str | None:
    """Return the link to hand the Docs API, or None to degrade the run to plain text.

    Docs normalises a URL that carries no scheme against its own origin, so a
    relative href ("./guide.md", "/guide.md") that this server passes through
    unchanged lands as "http://./guide.md" or "http://docs.google.com/guide.md" -
    a link that goes nowhere, reported as LK-12/EP-8 in the Markdown-fidelity
    baseline (#1120). A scheme-less target is therefore not storable: the text
    stays, the broken link is dropped.

    Any scheme counts, not a fixed list: "HTTPS://...", "tel:", "ftps://",
    "file://" and app links such as "vscode://" are working links today, so a
    lowercase allow-list would strip the target from links that do resolve.

    "#..." is allowed through because same-document heading anchors are
    resolved into full URLs by the _resolve_heading_anchors pass, which runs
    after the write (#409), and a "#slug" is a working in-doc link, not a
    relative file path.

    A scheme-less target that names a host is rewritten rather than dropped
    (#1180): "//example.com/x" becomes "https://example.com/x" and
    "www.example.com" becomes "https://www.example.com". Always https, never
    http: a host that only serves plain http loses the link, by design. The www
    rule runs before the scheme match, which would read "www.example.com:8443/x"
    as a "www.example.com:" scheme and pass it through for Docs to prefix with
    http://.
    """
    if link_url is None:
        return None
    url = link_url.strip()
    www = _BARE_WWW_LINK.fullmatch(url)
    if www and valid_gfm_domain(www.group(1)):
        return "https://" + url
    if url.startswith("#") or _STORABLE_LINK_SCHEME.match(url):
        return url
    if _HOST_RELATIVE_LINK.fullmatch(url):
        return "https:" + url
    return None


def _image_link_request(link_url: str, position: int) -> dict:
    """updateTextStyle linking the image just inserted at `position` (#977)."""
    return {
        "updateTextStyle": {
            "range": {"startIndex": position, "endIndex": position + 1},
            "textStyle": {"link": {"url": link_url}},
            "fields": "link",
        }
    }


def _run_style_requests(run: Run, start: int, end: int) -> list[dict]:
    """Return updateTextStyle requests for all non-None style fields on a Run."""
    text_style: dict = {}
    fields: list[str] = []

    for key, api_key in [
        ("bold", "bold"),
        ("italic", "italic"),
        ("underline", "underline"),
        ("strikethrough", "strikethrough"),
    ]:
        val = getattr(run, key)
        if val is not None:
            text_style[api_key] = val
            fields.append(api_key)

    link_url = _storable_link_url(run.link_url)
    if link_url is not None:
        text_style["link"] = {"url": link_url}
        fields.append("link")

    if run.font_family is not None:
        text_style["weightedFontFamily"] = {"fontFamily": run.font_family}
        fields.append("weightedFontFamily")

    if run.font_size is not None:
        text_style["fontSize"] = {"magnitude": run.font_size, "unit": "PT"}
        fields.append("fontSize")

    if run.foreground_color is not None:
        c = run.foreground_color
        text_style["foregroundColor"] = {
            "color": {"rgbColor": {"red": c.red, "green": c.green, "blue": c.blue}}
        }
        fields.append("foregroundColor")

    if run.background_color is not None:
        c = run.background_color
        text_style["backgroundColor"] = {
            "color": {"rgbColor": {"red": c.red, "green": c.green, "blue": c.blue}}
        }
        fields.append("backgroundColor")

    if run.baseline_offset is not None:
        text_style["baselineOffset"] = run.baseline_offset
        fields.append("baselineOffset")

    if run.small_caps is not None:
        text_style["smallCaps"] = run.small_caps
        fields.append("smallCaps")

    if not fields:
        return []

    return [
        {
            "updateTextStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "textStyle": text_style,
                "fields": ",".join(fields),
            }
        }
    ]


async def fill_tables(docs_service, doc_id: str, tables: list[Table], images: CellImages) -> None:
    """Fill table cells and apply inline styles using live cell indices.

    Phases:
      1. Re-fetch → get cell positions
      2. If any colspan/rowspan > 1: emit mergeTableCells, re-fetch
      3. Fill plain cells (no nested table) — insertText + updateTextStyle, high→low
      4. Fill cells with a nested table, segment by segment (see
         _fill_nested_cell_content) — text and tables in true source order,
         recursing into any depth of further nesting. Each nested table's own
         merges are handled by _fill_table_fully, mirroring phase 2 above (#109).
      5. If any table has a non-None col_width: re-fetch, then emit
         updateTableColumnProperties (skipping columns past the table's width)
      6. If any cell has Phase 3 style fields: emit updateTableCellStyle

    Phases 5 and 6 must use a doc fetched after phases 3 and 4: the fill shifts the
    startIndex of every table after the first, and a stale one is a 400 (#1053).
    They share one post-fill fetch, since column-width changes move no indices.

    images: the resolved images to embed in cells, at any nesting depth, and how each
    fill batch is sent (#1073).

    Nested table limitations: no col_widths inside nested tables. colspan/
    rowspan (#109) and text sharing a cell with one or more nested tables
    (#108, #275) are both fully supported, at any nesting depth — each run of
    text, merge, and nested table renders in the same order and shape it had
    in the source.
    """
    if not tables:
        return

    has_nested = any(
        any(isinstance(child, Table) for child in cell.children)
        for table in tables
        for row in table.rows
        for cell in row.cells
    )

    # Step 1: fetch doc; collapse blank paragraphs stranded immediately before tables (an
    # artifact of phase-1 insertText displacing the doc's initial empty paragraph).  The
    # Docs API rejects deleteContentRange on these paragraphs because a paragraph before a
    # table is structurally required, so we shrink them to zero visual height instead.
    live_doc = await execute_in_thread(
        docs_service.documents().get(documentId=doc_id).execute,
        docs_service,
    )
    blank_collapses = _build_blank_para_before_table_collapses(live_doc)
    if blank_collapses:
        await execute_in_thread(
            docs_service.documents()
            .batchUpdate(documentId=doc_id, body={"requests": blank_collapses})
            .execute,
            docs_service,
        )
        live_doc = await execute_in_thread(
            docs_service.documents().get(documentId=doc_id).execute,
            docs_service,
        )
    doc_tables = _top_level_tables(live_doc)

    # Step 2: outer merges
    doc_tables = await _apply_merges(docs_service, doc_id, doc_tables, tables, _top_level_tables)

    # Step 3: fill plain cells (no nested table) in one bulk batch
    fill_requests = _build_fill_requests(doc_tables, tables, images)
    if fill_requests:
        await images.execute(fill_requests)

    # Step 4: fill cells that contain a nested table, preserving true content order
    # at any nesting depth
    if has_nested:
        await _fill_nested_cell_content(docs_service, doc_id, tables, images)

    # Steps 5 and 6 need each table's startIndex as it is after the fill. Steps 3 and 4
    # inserted text into every earlier table's cells, so step 1's startIndex for any
    # table after the first is stale (#1053). Fetch once, after the fill, and share the
    # snapshot: updateTableColumnProperties moves no indices.
    post_fill_doc: dict | None = None

    # Step 5: column widths
    if any(w is not None for t in tables for w in t.col_widths):
        post_fill_doc = await execute_in_thread(
            docs_service.documents().get(documentId=doc_id).execute,
            docs_service,
        )
        width_requests = _build_width_requests(post_fill_doc, tables)
        if width_requests:
            await execute_in_thread(
                docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": width_requests})
                .execute,
                docs_service,
            )

    # Step 6: Phase 3 cell styling (background, padding, borders)
    has_cell_styles = any(
        cell.background_color is not None
        or cell.padding_top is not None
        or cell.padding_right is not None
        or cell.padding_bottom is not None
        or cell.padding_left is not None
        or cell.border_color is not None
        or cell.border_width is not None
        or cell.border_dash_style is not None
        for table in tables
        for row in table.rows
        for cell in row.cells
    )
    if has_cell_styles:
        if post_fill_doc is None:
            post_fill_doc = await execute_in_thread(
                docs_service.documents().get(documentId=doc_id).execute,
                docs_service,
            )
        doc_tables = _top_level_tables(post_fill_doc)
        cell_style_requests = _build_cell_style_requests(doc_tables, tables)
        if cell_style_requests:
            await execute_in_thread(
                docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": cell_style_requests})
                .execute,
                docs_service,
            )


def _top_level_tables(live_doc: dict) -> list[dict]:
    return [
        elem["table"] for elem in live_doc.get("body", {}).get("content", []) if "table" in elem
    ]


def _ast_cell_to_doc_cell(doc_table: dict, ast_table: Table, r: int, ast_col: int) -> dict | None:
    """Return the physical doc cell for logical (row=r, ast column=ast_col)."""
    doc_rows = doc_table.get("tableRows", [])
    if r >= len(doc_rows):
        return None
    phantom = _build_phantom_set(ast_table)
    ast_row = ast_table.rows[r]
    total_cols = max((sum(c.colspan for c in row.cells) for row in ast_table.rows), default=0)
    doc_cells = sorted(doc_rows[r].get("tableCells", []), key=lambda c: c.get("startIndex", 0))
    mapping = _physical_to_ast_indices(r, ast_row, phantom, total_cols)
    for doc_cell, ast_cell_idx in zip(doc_cells, mapping, strict=True):
        if ast_cell_idx == ast_col:
            return doc_cell
    return None


def _is_insertable_table(child: Run | Image | Table) -> bool:
    """A Table child only actually gets an insertTable shell (and thus a
    paragraph/table/paragraph split in the live doc) if it has at least one row
    and one column — see the `num_rows > 0 and num_cols > 0` guard where
    insertTable requests are built. A degenerate table (e.g. a row with no
    cells — reachable, pre-clamp-fix, via colspan="0"/rowspan="0" HTML) must
    NOT be counted as "already inserted" by cursor/paragraph-counting logic,
    or every later segment in the same cell resolves to the wrong paragraph.
    """
    if not isinstance(child, Table):
        return False
    num_rows = len(child.rows)
    num_cols = max((sum(c.colspan for c in row.cells) for row in child.rows), default=0)
    return num_rows > 0 and num_cols > 0


def _cell_para_start_for_cursor(doc_cell: dict, ast_cell: Cell, cursor: int) -> int | None:
    """Return the startIndex of the paragraph a cell's next unfilled segment belongs in.

    A cell's `content` alternates paragraph/table/paragraph/table/... — the Nth
    paragraph (0-indexed) is the one immediately after the Nth already-inserted
    nested table, where N = how many *insertable* Table children precede
    `cursor` (see _is_insertable_table). This is the paragraph's own
    startIndex — callers inserting a Table (not text) must add
    _text_offset_since_last_table() on top, since earlier text in the same
    paragraph (inserted in a prior round) isn't reflected in the paragraph's
    unchanged startIndex.
    """
    tables_before = sum(1 for child in ast_cell.children[:cursor] if _is_insertable_table(child))
    paragraphs = [elem for elem in doc_cell.get("content", []) if "paragraph" in elem]
    if tables_before >= len(paragraphs):
        return None
    return paragraphs[tables_before].get("startIndex")


def _text_offset_since_last_table(
    children: list[Run | Image | Table], cursor: int, image_uris: dict[int, str] | None = None
) -> int:
    """Sum of Run text lengths, plus one per embedded Image, between the nearest
    preceding *insertable* Table (exclusive) and cursor — a degenerate table is
    transparent here since it was never actually inserted (see _is_insertable_table).
    An Image counts only while it has an entry in `image_uris`: one never resolved, or
    dropped after its insert failed, isn't in the doc (#1073).

    A Table's insertion point is its paragraph's startIndex *plus* this offset,
    since any leading text already inserted into that same paragraph (in an
    earlier round) shifts where the table must land but doesn't change the
    paragraph's own startIndex.
    """
    offset = 0
    for i in range(cursor - 1, -1, -1):
        child = children[i]
        if _is_insertable_table(child):
            break
        if isinstance(child, Run):
            offset += utf16_len(child.text)
        elif isinstance(child, Image) and image_uris and id(child) in image_uris:
            offset += 1
    return offset


def _find_nth_table_in_cell(
    doc_table: dict, ast_table: Table, r: int, c: int, occurrence: int
) -> dict | None:
    """Return the `occurrence`-th (0-indexed) nested table element inside cell (r, c)."""
    doc_cell = _ast_cell_to_doc_cell(doc_table, ast_table, r, c)
    if doc_cell is None:
        return None
    nested_tables = [elem["table"] for elem in doc_cell.get("content", []) if "table" in elem]
    if occurrence >= len(nested_tables):
        return None
    return nested_tables[occurrence]


def _run_group_fill_requests(
    children: Sequence[Run | Image | Table], para_start: int, images: CellImages
) -> list[dict]:
    """Build insertText + updateTextStyle requests for a contiguous run of text, then
    an insertInlineImage for each of its resolved images (#1073). `children` holds no
    Table: a caller passes a cell's children only up to its next nested table.

    The images go last, latest position first, like ast_to_requests's positional
    pass: the text and its styles are placed as if no image were there, and each
    image lands at the offset of the text before it without shifting any image
    already placed. Two images with no text between them share an offset, so the
    later one goes in first and the earlier one then lands ahead of it."""
    runs = [child for child in children if isinstance(child, Run)]
    text = "".join(run.text for run in runs)
    requests: list[dict] = []
    if text:
        requests.extend(_text_fill_requests(runs, text, para_start))
    placed: list[tuple[int, Image]] = []
    offset = 0
    for child in children:
        if isinstance(child, Run):
            offset += utf16_len(child.text)
        elif id(child) in images.uris:
            placed.append((offset, child))
    for offset, image in reversed(placed):
        requests.extend(images.insert_requests(image, para_start + offset))
    return requests


def _text_fill_requests(runs: list[Run], text: str, para_start: int) -> list[dict]:
    requests: list[dict] = [
        {"insertText": {"location": {"index": para_start}, "text": text}},
        # Clear any fontSize inherited from a preceding heading — see _build_fill_requests.
        {
            "updateTextStyle": {
                "range": {"startIndex": para_start, "endIndex": para_start + utf16_len(text)},
                "textStyle": {},
                "fields": "fontSize",
            }
        },
    ]
    offset = 0
    for run in runs:
        run_len = utf16_len(run.text)
        if run_len > 0:
            requests.extend(
                _run_style_requests(run, para_start + offset, para_start + offset + run_len)
            )
        offset += run_len
    return requests


async def _fill_nested_cell_content(
    docs_service, doc_id: str, tables: list[Table], images: CellImages
) -> None:
    """Fill every cell that contains a nested table, preserving true content order.

    Cells with no nested table are handled in bulk by _build_fill_requests instead
    (faster, one batch for the whole document). This function only processes cells
    whose `children` include at least one Table, recursing into any depth of
    further nesting (#108, #275): each round emits one contiguous segment — a
    run of text or one nested table's shell — per still-pending cell, sorted
    high→low within the round, then re-fetches before the next round.
    """
    await _fill_children_recursive(
        docs_service, doc_id, lambda live_doc: _top_level_tables(live_doc), tables, images
    )


async def _fill_children_recursive(
    docs_service,
    doc_id: str,
    resolve,
    ast_tables: list[Table],
    images: CellImages,
    _doc_tables: list[dict] | None = None,
) -> None:
    """resolve(live_doc) -> doc_table dicts positionally matching ast_tables.

    _doc_tables: already-fetched, still-valid doc_tables to seed the first
    round with — pass this when the caller knows nothing has changed in the
    live doc since it last fetched, to avoid a redundant re-fetch.
    """
    pending: dict[tuple[int, int, int], int] = {}
    for t, table in enumerate(ast_tables):
        for r, row in enumerate(table.rows):
            for c, cell in enumerate(row.cells):
                if any(isinstance(child, Table) for child in cell.children):
                    pending[(t, r, c)] = 0
    if not pending:
        return

    if _doc_tables is not None:
        doc_tables = _doc_tables
    else:
        live_doc = await execute_in_thread(
            docs_service.documents().get(documentId=doc_id).execute,
            docs_service,
        )
        doc_tables = resolve(live_doc)

    while pending:
        round_requests: list[tuple[int, list[dict]]] = []
        table_inserts: list[tuple[int, int, int, int, Table]] = []  # (t, r, c, occurrence, table)
        done = []

        for (t, r, c), cursor in pending.items():
            doc_table = doc_tables[t] if t < len(doc_tables) else None
            ast_table = ast_tables[t]
            ast_cell = ast_table.rows[r].cells[c]
            children = ast_cell.children
            if doc_table is None or cursor >= len(children):
                done.append((t, r, c))
                continue
            doc_cell = _ast_cell_to_doc_cell(doc_table, ast_table, r, c)
            if doc_cell is None:
                done.append((t, r, c))
                continue
            para_start = _cell_para_start_for_cursor(doc_cell, ast_cell, cursor)
            if para_start is None:
                done.append((t, r, c))
                continue

            child = children[cursor]
            if isinstance(child, Table):
                num_rows = len(child.rows)
                num_cols = max(
                    (sum(cc.colspan for cc in row.cells) for row in child.rows), default=0
                )
                occurrence = sum(1 for ch in children[:cursor] if _is_insertable_table(ch))
                # Any text already inserted earlier this round-chain, in the same
                # paragraph, shifts the table's landing spot past that text.
                table_start = para_start + _text_offset_since_last_table(
                    children, cursor, images.uris
                )
                if num_rows > 0 and num_cols > 0:
                    round_requests.append(
                        (
                            table_start,
                            [
                                {
                                    "insertTable": {
                                        "rows": num_rows,
                                        "columns": num_cols,
                                        "location": {"index": table_start},
                                    }
                                }
                            ],
                        )
                    )
                    table_inserts.append((t, r, c, occurrence, child))
                new_cursor = cursor + 1
            else:
                # Consume every non-Table child (text and images, #1073) up to the
                # next Table. Stopping only at a Table guarantees j > cursor, so the
                # cell can't stay pending forever (#509).
                j = cursor
                group: list[Run | Image] = []
                while j < len(children):
                    next_child = children[j]
                    if isinstance(next_child, Table):
                        break
                    group.append(next_child)
                    j += 1
                reqs = _run_group_fill_requests(group, para_start, images)
                if reqs:
                    round_requests.append((para_start, reqs))
                new_cursor = j

            pending[(t, r, c)] = new_cursor
            if new_cursor >= len(children):
                done.append((t, r, c))

        for key in done:
            del pending[key]

        if round_requests:
            round_requests.sort(key=lambda x: x[0], reverse=True)
            batch = [req for _, reqs in round_requests for req in reqs]
            await images.execute(batch)
        # No `break` here even when a round emits no requests (e.g. a degenerate
        # zero-column table skipped by the `num_rows > 0 and num_cols > 0` guard
        # above): cursors still advance every round for every non-done cell, so
        # `pending` truthfulness alone correctly drives loop termination — a
        # `break` on empty round_requests would silently abandon any cells whose
        # only remaining work that round was such a skip.

        for t, r, c, occurrence, table_child in table_inserts:
            parent_resolve = resolve

            def child_resolve(live_doc, _resolve=parent_resolve, _t=t, _r=r, _c=c, _occ=occurrence):
                parent_tables = _resolve(live_doc)
                if _t >= len(parent_tables) or parent_tables[_t] is None:
                    return [None]
                return [_find_nth_table_in_cell(parent_tables[_t], ast_tables[_t], _r, _c, _occ)]

            # This performs its own batchUpdate(s), which shift indices for any
            # outer-cell content that comes after this nested table — the outer
            # loop's own doc_tables (re-fetched below) must reflect that.
            await _fill_table_fully(docs_service, doc_id, child_resolve, table_child, images)

        if pending:
            live_doc = await execute_in_thread(
                docs_service.documents().get(documentId=doc_id).execute,
                docs_service,
            )
            doc_tables = resolve(live_doc)


async def _fill_table_fully(
    docs_service, doc_id: str, resolve, ast_table: Table, images: CellImages
) -> None:
    """Fill one (typically just-inserted) table's cells: merges first, then
    plain cells in bulk, then cells with a further nested table via the
    recursive round algorithm.

    Every nested table needs this — not just ones with further nesting — since
    a nested table's own plain-text cells (and merges) are never touched by the
    top-level fill_tables passes (those only see the outer tables list).
    """
    live_doc = await execute_in_thread(
        docs_service.documents().get(documentId=doc_id).execute,
        docs_service,
    )
    doc_tables = resolve(live_doc)
    if not doc_tables or doc_tables[0] is None:
        logger.debug(
            "_fill_table_fully: could not locate nested table in live doc %s — "
            "skipping fill for this table (it will render as an empty shell)",
            doc_id,
        )
        return

    doc_tables = await _apply_merges(docs_service, doc_id, doc_tables, [ast_table], resolve)

    fill_requests = _build_fill_requests(doc_tables, [ast_table], images)
    if fill_requests:
        await images.execute(fill_requests)
        # The bulk fill just shifted indices — the recursive call must re-fetch.
        await _fill_children_recursive(docs_service, doc_id, resolve, [ast_table], images)
    else:
        # Nothing changed since doc_tables was fetched above — reuse it instead
        # of having the recursive call redundantly re-fetch identical data.
        await _fill_children_recursive(
            docs_service, doc_id, resolve, [ast_table], images, _doc_tables=doc_tables
        )


async def _apply_merges(
    docs_service, doc_id: str, doc_tables: list[dict], ast_tables: list[Table], resolve
) -> list[dict]:
    """Emit mergeTableCells for any ast_tables cell with colspan/rowspan > 1,
    re-fetch, and return the updated doc_tables — or doc_tables unchanged if
    nothing needed merging.

    mergeTableCells doesn't shift character indices or delete content (covered
    cells remain physical entries in the doc tree), so doc_tables — already
    successfully resolved by the caller — is expected to resolve again right
    after. If it doesn't, the live doc no longer matches the model used to
    build the merge requests just executed; silently returning here would mean
    every already-merged table renders with zero content and no operator-
    visible signal, so raise instead of skipping the fill.
    """
    has_merges = any(
        cell.colspan > 1 or cell.rowspan > 1
        for table in ast_tables
        for row in table.rows
        for cell in row.cells
    )
    if not has_merges:
        return doc_tables

    merge_requests = _build_merge_requests(doc_tables, ast_tables)
    if not merge_requests:
        return doc_tables

    await execute_in_thread(
        docs_service.documents()
        .batchUpdate(documentId=doc_id, body={"requests": merge_requests})
        .execute,
        docs_service,
    )
    live_doc = await execute_in_thread(
        docs_service.documents().get(documentId=doc_id).execute,
        docs_service,
    )
    updated = resolve(live_doc)
    if len(updated) < len(ast_tables) or any(t is None for t in updated):
        raise RuntimeError(
            f"_apply_merges: table(s) vanished from doc {doc_id} immediately after "
            "mergeTableCells, which does not itself shift indices or delete content — "
            "refusing to silently skip the fill and leave the merged table empty."
        )
    return updated


def _build_phantom_set(ast_table: Table) -> set[tuple[int, int]]:
    """Return (row, col) logical positions covered by rowspan from a cell in an earlier row."""
    phantom: set[tuple[int, int]] = set()
    for r, ast_row in enumerate(ast_table.rows):
        col = 0
        for ast_cell in ast_row.cells:
            while (r, col) in phantom:
                col += 1
            for dr in range(ast_cell.rowspan):
                for dc in range(ast_cell.colspan):
                    if dr > 0 or dc > 0:
                        phantom.add((r + dr, col + dc))
            col += ast_cell.colspan
    return phantom


def _physical_to_ast_indices(
    r: int, ast_row: Row, phantom: set[tuple[int, int]], total_cols: int
) -> list[int | None]:
    """Map each physical doc cell index in row r to an AST cell index, or None if phantom.

    Physical cells = all logical columns except colspan-absorbed ones.
    Rowspan phantom cells are still physical (present in the doc after merge) but are skipped.
    """
    # Determine which logical cols are absorbed by colspan (not physical cells)
    absorbed: set[int] = set()
    logical_col = 0
    for ast_cell in ast_row.cells:
        while (r, logical_col) in phantom:
            logical_col += 1
        for dc in range(1, ast_cell.colspan):
            absorbed.add(logical_col + dc)
        logical_col += ast_cell.colspan

    mapping: list[int | None] = []
    ast_idx = 0
    for col in range(total_cols):
        if col in absorbed:
            # Colspan phantom — remains as a physical cell in the doc after mergeTableCells,
            # just like a rowspan phantom. Map to None so it gets skipped during fill.
            mapping.append(None)
        elif (r, col) in phantom:
            mapping.append(None)  # rowspan phantom — physical but owned by an earlier row
        else:
            mapping.append(ast_idx)
            ast_idx += 1
    return mapping


def _build_merge_requests(doc_tables: list[dict], ast_tables: list[Table]) -> list[dict]:
    """Emit mergeTableCells for any cell with colspan > 1 or rowspan > 1."""
    requests: list[dict] = []
    for doc_table, ast_table in zip(doc_tables, ast_tables, strict=True):
        table_start = _table_start_index(doc_table)
        if table_start is None:
            continue

        phantom = _build_phantom_set(ast_table)

        for r, ast_row in enumerate(ast_table.rows):
            logical_col = 0
            # Each colspan merge removes (colspan-1) physical cells from this row;
            # rowspan phantoms remain as physical cells and don't shift column indices.
            colspan_removed = 0
            for ast_cell in ast_row.cells:
                while (r, logical_col) in phantom:
                    logical_col += 1
                if ast_cell.colspan > 1 or ast_cell.rowspan > 1:
                    physical_col = logical_col - colspan_removed
                    requests.append(
                        {
                            "mergeTableCells": {
                                "tableRange": {
                                    "tableCellLocation": {
                                        "tableStartLocation": {"index": table_start},
                                        "rowIndex": r,
                                        "columnIndex": physical_col,
                                    },
                                    "rowSpan": ast_cell.rowspan,
                                    "columnSpan": ast_cell.colspan,
                                }
                            }
                        }
                    )
                if ast_cell.colspan > 1:
                    colspan_removed += ast_cell.colspan - 1
                logical_col += ast_cell.colspan
    return requests


def _build_fill_requests(
    doc_tables: list[dict], ast_tables: list[Table], images: CellImages
) -> list[dict]:
    """Build insertText + updateTextStyle requests for cells with no nested table,
    sorted high→low, so they can all be emitted in one batch. Cells that contain a
    nested table are skipped here — _fill_nested_cell_content handles those instead,
    since a nested table needs its own live-index re-fetch cycle.
    """
    all_requests: list[tuple[int, list[dict]]] = []

    for doc_table, ast_table in zip(doc_tables, ast_tables, strict=True):
        doc_rows = doc_table.get("tableRows", [])
        phantom = _build_phantom_set(ast_table)
        total_cols = max((sum(c.colspan for c in row.cells) for row in ast_table.rows), default=0)
        if total_cols == 0:
            continue

        for r, (doc_row_entry, ast_row) in enumerate(zip(doc_rows, ast_table.rows, strict=True)):
            # Sort by startIndex: after mergeTableCells, the API may return covered
            # (phantom) cells last rather than in column order.
            doc_cells = sorted(
                doc_row_entry.get("tableCells", []), key=lambda c: c.get("startIndex", 0)
            )
            mapping = _physical_to_ast_indices(r, ast_row, phantom, total_cols)

            for doc_cell, ast_cell_idx in zip(doc_cells, mapping, strict=True):
                if ast_cell_idx is None:
                    continue  # rowspan phantom — skip
                ast_cell = ast_row.cells[ast_cell_idx]
                if any(isinstance(child, Table) for child in ast_cell.children):
                    continue  # handled by _fill_nested_cell_content instead
                cell_content = doc_cell.get("content", [])
                if not cell_content:
                    continue
                para_start = cell_content[0].get("startIndex")
                if para_start is None:
                    continue

                cell_requests = _run_group_fill_requests(ast_cell.children, para_start, images)
                if cell_requests:
                    all_requests.append((para_start, cell_requests))

    all_requests.sort(key=lambda x: x[0], reverse=True)
    return [req for _, reqs in all_requests for req in reqs]


def _build_cell_style_requests(doc_tables: list[dict], ast_tables: list[Table]) -> list[dict]:
    """Build updateTableCellStyle requests for cells with Phase 3 style fields set."""
    requests: list[dict] = []

    def _rgb(color) -> dict:
        return {"color": {"rgbColor": {"red": color.red, "green": color.green, "blue": color.blue}}}

    def _pt(magnitude: float) -> dict:
        return {"magnitude": magnitude, "unit": "PT"}

    for doc_table, ast_table in zip(doc_tables, ast_tables, strict=True):
        table_start = _table_start_index(doc_table)
        if table_start is None:
            continue
        phantom = _build_phantom_set(ast_table)
        total_cols = max((sum(c.colspan for c in row.cells) for row in ast_table.rows), default=0)
        if total_cols == 0:
            continue

        for r, ast_row in enumerate(ast_table.rows):
            mapping = _physical_to_ast_indices(r, ast_row, phantom, total_cols)
            for col, ast_cell_idx in enumerate(mapping):
                if ast_cell_idx is None:
                    continue
                ast_cell = ast_row.cells[ast_cell_idx]

                cell_style: dict = {}
                style_fields: list[str] = []

                if ast_cell.background_color is not None:
                    cell_style["backgroundColor"] = _rgb(ast_cell.background_color)
                    style_fields.append("backgroundColor")

                if ast_cell.padding_top is not None:
                    cell_style["paddingTop"] = _pt(ast_cell.padding_top)
                    style_fields.append("paddingTop")
                if ast_cell.padding_right is not None:
                    cell_style["paddingRight"] = _pt(ast_cell.padding_right)
                    style_fields.append("paddingRight")
                if ast_cell.padding_bottom is not None:
                    cell_style["paddingBottom"] = _pt(ast_cell.padding_bottom)
                    style_fields.append("paddingBottom")
                if ast_cell.padding_left is not None:
                    cell_style["paddingLeft"] = _pt(ast_cell.padding_left)
                    style_fields.append("paddingLeft")

                if any([ast_cell.border_color, ast_cell.border_width, ast_cell.border_dash_style]):
                    border: dict = {}
                    if ast_cell.border_color is not None:
                        border["color"] = _rgb(ast_cell.border_color)
                    if ast_cell.border_width is not None:
                        border["width"] = _pt(ast_cell.border_width)
                    if ast_cell.border_dash_style is not None:
                        border["dashStyle"] = ast_cell.border_dash_style
                    for side in ("borderTop", "borderBottom", "borderLeft", "borderRight"):
                        cell_style[side] = border
                        style_fields.append(side)

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
                                    "columnIndex": col,
                                },
                                "rowSpan": 1,
                                "columnSpan": 1,
                            },
                        }
                    }
                )

    return requests


def _build_width_requests(live_doc: dict, ast_tables: list[Table]) -> list[dict]:
    """Build updateTableColumnProperties requests for tables with col_widths."""
    requests: list[dict] = []
    doc_table_elems = [
        elem for elem in live_doc.get("body", {}).get("content", []) if "table" in elem
    ]

    for elem, ast_table in zip(doc_table_elems, ast_tables, strict=True):
        if not ast_table.col_widths:
            continue
        table_start = elem.get("startIndex")
        if table_start is None:
            continue
        # More <col> widths than cells is valid HTML, but an index past the table's
        # last column is a 400 that fails the whole batch.
        table = elem["table"]
        num_cols = table.get("columns") or max(
            (len(row.get("tableCells", [])) for row in table.get("tableRows", [])), default=0
        )
        for col_idx, width_pt in enumerate(ast_table.col_widths[:num_cols]):
            if width_pt is None:
                continue
            requests.append(
                {
                    "updateTableColumnProperties": {
                        "tableStartLocation": {"index": table_start},
                        "columnIndices": [col_idx],
                        "tableColumnProperties": {
                            "widthType": "FIXED_WIDTH",
                            "width": {"magnitude": width_pt, "unit": "PT"},
                        },
                        "fields": "width,widthType",
                    }
                }
            )

    return requests


def _build_blank_para_before_table_collapses(live_doc: dict) -> list[dict]:
    """Return requests that reset empty paragraphs immediately before tables to a plain
    paragraph and collapse them to zero visual height.

    Phase-1 insertText displaces the doc's initial empty paragraph, leaving a blank line
    stranded between the preceding content and the table.  deleteContentRange is rejected by
    the Docs API for these paragraphs (a paragraph before a table is structurally required),
    so we shrink them instead: spaceAbove/Below = 0, lineSpacing = 1 (1% of normal),
    fontSize = 1 pt, namedStyleType = NORMAL_TEXT (the displaced paragraph inherits the
    preceding heading's style, #1092), no bullet and no indent or border (see below).  Only
    paragraphs whose sole content is a newline are affected, and one sitting between two
    tables is reset but keeps its height (#1098).
    """
    content = live_doc.get("body", {}).get("content", [])
    requests: list[dict] = []
    for i, elem in enumerate(content):
        if "table" not in elem or i == 0:
            continue
        prev = content[i - 1]
        if "paragraph" not in prev:
            continue
        para_text = "".join(
            el.get("textRun", {}).get("content", "") for el in prev["paragraph"].get("elements", [])
        )
        if para_text != "\n":
            continue
        start = prev.get("startIndex")
        end = prev.get("endIndex")
        if start is None or end is None:
            continue
        rng = {"startIndex": start, "endIndex": end}
        # insertTable gives the paragraph it adds the style of the paragraph at the
        # insertion point. That's the table's plain placeholder now (#1097), but before
        # it was the block after the table: a following list's bullet (a visible empty
        # item, and the list numbered from 2 or 3), a following quote's indent and
        # border. Reset all of it anyway, as a backstop. deleteParagraphBullets adds
        # indent to keep a paragraph's visual level, so the indent reset must come after.
        requests.append({"deleteParagraphBullets": {"range": rng}})
        requests.append(
            {
                "updateParagraphStyle": {
                    "range": rng,
                    # Named in fields but absent from paragraphStyle: reset to default.
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    "fields": "namedStyleType,indentStart,indentFirstLine,borderLeft",
                }
            }
        )
        if i >= 2 and "table" in content[i - 2]:
            # The only thing between two tables: collapsed, the tables touched and read
            # as one (#1098). Left at full height, it's the blank line between them.
            continue
        requests.extend(_collapse_paragraph_requests(rng))
    return requests


def _table_start_index(doc_table: dict) -> int | None:
    """Return the tableStartLocation index for a doc table element."""
    rows = doc_table.get("tableRows", [])
    if not rows:
        return None
    cells = rows[0].get("tableCells", [])
    if not cells:
        return None
    return cells[0].get("startIndex", 1) - 2  # rough: table startIndex = first cell - 2
