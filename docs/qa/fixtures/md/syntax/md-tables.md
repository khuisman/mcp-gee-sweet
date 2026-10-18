### TB-01 — basic table

| Name | Role |
|------|------|
| Ana  | Lead |
| Ben  | Dev  |

### TB-02 — column alignment

| Left | Center | Right |
|:-----|:------:|------:|
| a    | b      | c     |
| left text | centered text | right text |

### TB-03 — inline formatting and links in cells

| Style | Example |
|-------|---------|
| Bold | **bold cell** |
| Italic | *italic cell* |
| Code | `code cell` |
| Strike | ~~struck cell~~ |
| Link | [cell link](https://example.com/cell) |
| Mixed | **bold** and `code` and [link](https://example.com/mix) |

### TB-04 — escaped pipe in a cell

| Expression | Meaning |
|------------|---------|
| `a \| b` | a or b |
| x \| y | pipe in plain text |

### TB-05 — empty cells

| A | B | C |
|---|---|---|
| 1 |   | 3 |
|   | 2 |   |

### TB-06 — ragged rows (too few and too many cells)

| A | B | C |
|---|---|---|
| only one |
| 1 | 2 | 3 | 4 |

### TB-07 — table directly after a heading, no blank line

#### Heading before table
| H1 | H2 |
|----|----|
| a  | b  |

### TB-08 — table directly after a paragraph, no blank line

Paragraph before the table.
| H1 | H2 |
|----|----|
| a  | b  |

### TB-09 — wide table (8 columns)

| C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 |
|----|----|----|----|----|----|----|----|
| alpha | bravo | charlie | delta | echo | foxtrot | golf | hotel |
| 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |

### TB-10 — table without leading and trailing pipes

Name | Score
--- | ---:
Ana | 91
Ben | 87

### TB-11 — two tables back to back

| T1 |
|----|
| a  |

| T2 |
|----|
| b  |

### TB-12 — table with long cell text that wraps

| Item | Notes |
|------|-------|
| Long | This cell has enough text that it must wrap across several lines inside the cell when rendered at normal page width. |
