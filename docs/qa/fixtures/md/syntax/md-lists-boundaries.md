### LX-01 — bullet list right after a paragraph, no blank line

Things to bring:
- A laptop
- A charger

### LX-02 — numbered list right after a paragraph, no blank line

Steps:
1. Open the app
2. Sign in

### LX-03 — list right after a heading, no blank line

#### Heading before list
- First
- Second

### LX-04 — paragraph right after a list, no blank line

- Last item
Paragraph after the list without a blank line.

### LX-05 — two bullet lists separated by an HTML comment

- First list, item one
- First list, item two

<!-- end of first list -->

- Second list, item one

### LX-06 — two numbered lists separated by a paragraph

1. Alpha one
2. Alpha two

A paragraph between the lists.

1. Beta one
2. Beta two

### LX-07 — bullet list then numbered list, blank line only

- Bullet item

1. Numbered item

### LX-08 — numbered list continues across a code block inside an item

1. Step one

   ```
   code for step one
   ```

2. Step two
3. Step three

### LX-09 — numbered list interrupted by an unindented code block

1. Step one

```
unindented code block
```

2. Step two (a new list per CommonMark; renders starting at 2)

### LX-10 — three sublists under one numbered item

1. Top one
    1. Child one
    2. Child two
    - Bullet child
    1. New child one
2. Top two
