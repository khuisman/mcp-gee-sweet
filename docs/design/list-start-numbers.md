# List Start Numbers

**Date:** 2026-11-03. **Issue:** #1118.

`3. a` produces `<ol start="3">`, and the Doc numbered it 1, 2. This doc records what the API
allows and why the fix has two mechanisms.

## What the API allows (checked live, 2026-11-03)

| Attempt | Result |
|---|---|
| A request that writes `NestingLevel.startNumber` | None exists in the `batchUpdate` request list (discovery revision 20261028) |
| A numbered preset with an offset | None in `createParagraphBullets`' `bulletPreset` enum |
| Create throwaway items, then delete them | Rejected: the rest renumber, `startNumber` stays 1 |
| Drive import of `<ol start="3">` | Sets `startNumber` 3, with `glyphType` unspecified and a 30/12pt indent |
| Text inserted inside an imported list | Stays in that list, and the list keeps its start after the original items are deleted |
| `createParagraphBullets` right after an imported list | Does not join it: a new list at 1 |
| `files.update` with HTML over an existing Doc | Works, but removes the headers, resets named styles and margins |

## Decision

1. **Continue the last list where that's the right number.** Docs numbers a list by `listId`, past
   anything between its items (#1094). A top-level list that starts exactly where the last top-level
   list stopped, in the same quote, is bulleted with it, and the blocks between are taken back out.
   That fixes LX-09 with a real list. Two lists in a row with different markers (`1. a`, `2) b`) are
   covered too, since the second starts where the first stopped.
2. **Otherwise write the numbers as text.** The item becomes `<number>.<tab><text>` at the list
   level's hanging indent. The tab reaches `indentStart`, so a literal list lines up with a real one
   (compared in a PDF render). A nested one uses its level's glyph, since a real sublist there shows
   letters or roman numerals. This keeps the numbers right at every entry point, in new and existing
   Docs alike, at the cost of not being a Docs list. The maintainer chose this over the alternatives
   below.

## Rejected

- **Seeding a list through Drive's import.** It only works for a new Doc, because over an existing
  one it destroys the Doc's styles, so `write_doc_content` and `update_doc_from_file` would still
  show the wrong numbers. Every other step would have to change too: seeds must sit where each list
  goes, and text would be inserted into them rather than bulleted, with a different indent and glyph.
- **Leaving it as a known limitation.** LM-04 would keep failing, on the ticket's own done-when.
- **Keeping throwaway items, hidden.** They'd show up in exports and in `get_doc_as_markdown`.

## Read side

`doc_to_ast._literal_item` turns a stand-in back into a `BulletItem`, so the export says `3. Three`
rather than the escaped `3\.` a paragraph would get. It needs the whole signature: no bullet, the
hanging indent, and the marker that level writes. A quoted stand-in's indent can't separate its list
level from its quote depth, so it reads as level 0 in a deeper quote.

An AST from `document_to_ast` never reaches the emitter with `list_path` set, so
`_resolve_list_starts` leaves its numbered items alone.
