# List gaps

### LG-01 — an intro line and a paragraph after the list

Install the headers:

- one
- two

Plain paragraph after the list.

### LG-02 — a list ending in a nested item

1. first
2. second
   - nested last

Paragraph after the nested item.

### LG-03 — a paragraph inside an item, its sublist, and the next item

1. first

   Paragraph inside first.

   - sub item

   Back in first.

2. second

### LG-04 — a paragraph between a list and its continuation

1. one

Between the list and its continuation.

2. two

Paragraph after the continued list.

### LG-05 — no gap at a heading item, a code block or a quote

- # Heading item

Paragraph after the heading item.

- item with code:

  ```
  code at the list's edge
  ```

Paragraph after the code block.

> Quoted intro:
>
> - quoted item
>
> Quoted paragraph after.

### LG-06 — a paragraph in one list's last item, then another list

- a

  Paragraph inside a.

1. b starts a new list

- c
  - c1

    Paragraph inside c1.

  - c2

### LG-07 — a paragraph in one list's last item, then a list starting at 3

- d

  Paragraph inside d.

3. literal list starting at 3

   Paragraph inside 3.

4. next literal item
