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

### LX-11 — a numbered marker change starts a new list

1. Dot one
2. Dot two

1) Paren one

1. Parent one
    1. Dot child
    1) Paren child
2. Parent two

### LX-12 — numbered sublist after a deeper numbered list

1. Outer one
   - Bullet child
     1. Deep child
   1. Restarted child
2. Outer two

### LX-13 — a list ends with a sublist of the other type

- First bullet
  - Bullet child
- Last bullet
  1. Numbered child one
  2. Numbered child two

### LX-14 — a list resumes past a quote and a heading

1. Resume one

> Quoted between the lists

#### Heading between the lists

2. Resume two
3. Resume three

### LX-15 — a list after another list can't resume the first

1. Numbered first

- Bullet between

2. Numbered second

### LX-16 — a list that doesn't pick up the count

1. Counted one

A paragraph between.

7. Skips to seven, wrapping onto a second line so its hanging indent shows on screen, with enough words here to reach the far margin of the page and carry on past it
   - Bullet under seven

   A second paragraph in seven.

8. **Bold** eight

### LX-17 — a sublist that doesn't start at 1

1. Parent one

   3. Child three
   4. Child four

2. Parent two

### LX-18 — a tab-indented code line between two lists

1. Tab one

```
	code starting with a tab
```

2. Tab two

A paragraph after.

### LX-19 — a tab-indented code line inside an item

1. Inner one

   ```
   	code starting with a tab
   ```

2. Inner two

### LX-20 — a table between two lists

1. Before the table

| x |
|---|
| y |

2. After the table

### LX-21 — a three-digit start

100. Hundred, wrapping onto a second line so its hanging indent shows on screen, with enough words here to reach the far margin of the page and carry on past it
101. Hundred and one
