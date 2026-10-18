# Containment matrix: every block inside every container

Contained content is indented 4 spaces per list level (valid in CommonMark and
Python-Markdown alike), so a failure here is about containment, not indent width.

### CT-01 — paragraph inside bullet item, level 0

- Container item

    Plain paragraph text.

- Sibling after

### CT-02 — heading inside bullet item, level 0

- Container item
    #### Inner heading
- Sibling after

### CT-03 — bullet list inside bullet item, level 0

- Container item
    - Bullet A
    - Bullet B
- Sibling after

### CT-04 — numbered list inside bullet item, level 0

- Container item
    1. Number A
    2. Number B
- Sibling after

### CT-05 — task list inside bullet item, level 0

- Container item
    - [ ] Task A
    - [x] Task B
- Sibling after

### CT-06 — code block inside bullet item, level 0

- Container item
    ```
    code line
    ```
- Sibling after

### CT-07 — blockquote inside bullet item, level 0

- Container item
    > Quoted line
- Sibling after

### CT-08 — table inside bullet item, level 0

- Container item

    | K | V |
    |---|---|
    | k1 | v1 |

- Sibling after

### CT-09 — image inside bullet item, level 0

- Container item

    ![pixel](https://www.gstatic.com/images/branding/product/2x/docs_48dp.png)

- Sibling after

### CT-10 — rule inside bullet item, level 0

- Container item
    ***
- Sibling after

### CT-11 — paragraph inside bullet item, level 1

- Top item
    - Container item

        Plain paragraph text.

    - Sibling after
- Top after

### CT-12 — heading inside bullet item, level 1

- Top item
    - Container item
        #### Inner heading
    - Sibling after
- Top after

### CT-13 — bullet list inside bullet item, level 1

- Top item
    - Container item
        - Bullet A
        - Bullet B
    - Sibling after
- Top after

### CT-14 — numbered list inside bullet item, level 1

- Top item
    - Container item
        1. Number A
        2. Number B
    - Sibling after
- Top after

### CT-15 — task list inside bullet item, level 1

- Top item
    - Container item
        - [ ] Task A
        - [x] Task B
    - Sibling after
- Top after

### CT-16 — code block inside bullet item, level 1

- Top item
    - Container item
        ```
        code line
        ```
    - Sibling after
- Top after

### CT-17 — blockquote inside bullet item, level 1

- Top item
    - Container item
        > Quoted line
    - Sibling after
- Top after

### CT-18 — table inside bullet item, level 1

- Top item
    - Container item

        | K | V |
        |---|---|
        | k1 | v1 |

    - Sibling after
- Top after

### CT-19 — image inside bullet item, level 1

- Top item
    - Container item

        ![pixel](https://www.gstatic.com/images/branding/product/2x/docs_48dp.png)

    - Sibling after
- Top after

### CT-20 — rule inside bullet item, level 1

- Top item
    - Container item
        ***
    - Sibling after
- Top after

### CT-21 — paragraph inside bullet item, level 2

- Top item
    - Mid item
        - Container item

            Plain paragraph text.

        - Sibling after
    - Mid after
- Top after

### CT-22 — heading inside bullet item, level 2

- Top item
    - Mid item
        - Container item
            #### Inner heading
        - Sibling after
    - Mid after
- Top after

### CT-23 — bullet list inside bullet item, level 2

- Top item
    - Mid item
        - Container item
            - Bullet A
            - Bullet B
        - Sibling after
    - Mid after
- Top after

### CT-24 — numbered list inside bullet item, level 2

- Top item
    - Mid item
        - Container item
            1. Number A
            2. Number B
        - Sibling after
    - Mid after
- Top after

### CT-25 — task list inside bullet item, level 2

- Top item
    - Mid item
        - Container item
            - [ ] Task A
            - [x] Task B
        - Sibling after
    - Mid after
- Top after

### CT-26 — code block inside bullet item, level 2

- Top item
    - Mid item
        - Container item
            ```
            code line
            ```
        - Sibling after
    - Mid after
- Top after

### CT-27 — blockquote inside bullet item, level 2

- Top item
    - Mid item
        - Container item
            > Quoted line
        - Sibling after
    - Mid after
- Top after

### CT-28 — table inside bullet item, level 2

- Top item
    - Mid item
        - Container item

            | K | V |
            |---|---|
            | k1 | v1 |

        - Sibling after
    - Mid after
- Top after

### CT-29 — image inside bullet item, level 2

- Top item
    - Mid item
        - Container item

            ![pixel](https://www.gstatic.com/images/branding/product/2x/docs_48dp.png)

        - Sibling after
    - Mid after
- Top after

### CT-30 — rule inside bullet item, level 2

- Top item
    - Mid item
        - Container item
            ***
        - Sibling after
    - Mid after
- Top after

### CT-31 — paragraph inside numbered item, level 0

1. Container item

    Plain paragraph text.

2. Sibling after

### CT-32 — heading inside numbered item, level 0

1. Container item
    #### Inner heading
2. Sibling after

### CT-33 — bullet list inside numbered item, level 0

1. Container item
    - Bullet A
    - Bullet B
2. Sibling after

### CT-34 — numbered list inside numbered item, level 0

1. Container item
    1. Number A
    2. Number B
2. Sibling after

### CT-35 — task list inside numbered item, level 0

1. Container item
    - [ ] Task A
    - [x] Task B
2. Sibling after

### CT-36 — code block inside numbered item, level 0

1. Container item
    ```
    code line
    ```
2. Sibling after

### CT-37 — blockquote inside numbered item, level 0

1. Container item
    > Quoted line
2. Sibling after

### CT-38 — table inside numbered item, level 0

1. Container item

    | K | V |
    |---|---|
    | k1 | v1 |

2. Sibling after

### CT-39 — image inside numbered item, level 0

1. Container item

    ![pixel](https://www.gstatic.com/images/branding/product/2x/docs_48dp.png)

2. Sibling after

### CT-40 — rule inside numbered item, level 0

1. Container item
    ***
2. Sibling after

### CT-41 — paragraph inside numbered item, level 1

1. Top item
    1. Container item

        Plain paragraph text.

    2. Sibling after
2. Top after

### CT-42 — heading inside numbered item, level 1

1. Top item
    1. Container item
        #### Inner heading
    2. Sibling after
2. Top after

### CT-43 — bullet list inside numbered item, level 1

1. Top item
    1. Container item
        - Bullet A
        - Bullet B
    2. Sibling after
2. Top after

### CT-44 — numbered list inside numbered item, level 1

1. Top item
    1. Container item
        1. Number A
        2. Number B
    2. Sibling after
2. Top after

### CT-45 — task list inside numbered item, level 1

1. Top item
    1. Container item
        - [ ] Task A
        - [x] Task B
    2. Sibling after
2. Top after

### CT-46 — code block inside numbered item, level 1

1. Top item
    1. Container item
        ```
        code line
        ```
    2. Sibling after
2. Top after

### CT-47 — blockquote inside numbered item, level 1

1. Top item
    1. Container item
        > Quoted line
    2. Sibling after
2. Top after

### CT-48 — table inside numbered item, level 1

1. Top item
    1. Container item

        | K | V |
        |---|---|
        | k1 | v1 |

    2. Sibling after
2. Top after

### CT-49 — image inside numbered item, level 1

1. Top item
    1. Container item

        ![pixel](https://www.gstatic.com/images/branding/product/2x/docs_48dp.png)

    2. Sibling after
2. Top after

### CT-50 — rule inside numbered item, level 1

1. Top item
    1. Container item
        ***
    2. Sibling after
2. Top after

### CT-51 — paragraph inside numbered item, level 2

1. Top item
    1. Mid item
        1. Container item

            Plain paragraph text.

        2. Sibling after
    2. Mid after
2. Top after

### CT-52 — heading inside numbered item, level 2

1. Top item
    1. Mid item
        1. Container item
            #### Inner heading
        2. Sibling after
    2. Mid after
2. Top after

### CT-53 — bullet list inside numbered item, level 2

1. Top item
    1. Mid item
        1. Container item
            - Bullet A
            - Bullet B
        2. Sibling after
    2. Mid after
2. Top after

### CT-54 — numbered list inside numbered item, level 2

1. Top item
    1. Mid item
        1. Container item
            1. Number A
            2. Number B
        2. Sibling after
    2. Mid after
2. Top after

### CT-55 — task list inside numbered item, level 2

1. Top item
    1. Mid item
        1. Container item
            - [ ] Task A
            - [x] Task B
        2. Sibling after
    2. Mid after
2. Top after

### CT-56 — code block inside numbered item, level 2

1. Top item
    1. Mid item
        1. Container item
            ```
            code line
            ```
        2. Sibling after
    2. Mid after
2. Top after

### CT-57 — blockquote inside numbered item, level 2

1. Top item
    1. Mid item
        1. Container item
            > Quoted line
        2. Sibling after
    2. Mid after
2. Top after

### CT-58 — table inside numbered item, level 2

1. Top item
    1. Mid item
        1. Container item

            | K | V |
            |---|---|
            | k1 | v1 |

        2. Sibling after
    2. Mid after
2. Top after

### CT-59 — image inside numbered item, level 2

1. Top item
    1. Mid item
        1. Container item

            ![pixel](https://www.gstatic.com/images/branding/product/2x/docs_48dp.png)

        2. Sibling after
    2. Mid after
2. Top after

### CT-60 — rule inside numbered item, level 2

1. Top item
    1. Mid item
        1. Container item
            ***
        2. Sibling after
    2. Mid after
2. Top after

### CT-61 — paragraph inside blockquote

> Container quote line
>
> Plain paragraph text.

### CT-62 — heading inside blockquote

> Container quote line
>
> #### Inner heading

### CT-63 — bullet list inside blockquote

> Container quote line
>
> - Bullet A
> - Bullet B

### CT-64 — numbered list inside blockquote

> Container quote line
>
> 1. Number A
> 2. Number B

### CT-65 — task list inside blockquote

> Container quote line
>
> - [ ] Task A
> - [x] Task B

### CT-66 — code block inside blockquote

> Container quote line
>
> ```
> code line
> ```

### CT-67 — blockquote inside blockquote

> Container quote line
>
> > Quoted line

### CT-68 — table inside blockquote

> Container quote line
>
> | K | V |
> |---|---|
> | k1 | v1 |

### CT-69 — image inside blockquote

> Container quote line
>
> ![pixel](https://www.gstatic.com/images/branding/product/2x/docs_48dp.png)

### CT-70 — rule inside blockquote

> Container quote line
>
> ***

### CT-71 — paragraph inside nested blockquote (depth 2)

> Outer quote
>
> > Container quote line
> >
> > Plain paragraph text.

### CT-72 — heading inside nested blockquote (depth 2)

> Outer quote
>
> > Container quote line
> >
> > #### Inner heading

### CT-73 — bullet list inside nested blockquote (depth 2)

> Outer quote
>
> > Container quote line
> >
> > - Bullet A
> > - Bullet B

### CT-74 — numbered list inside nested blockquote (depth 2)

> Outer quote
>
> > Container quote line
> >
> > 1. Number A
> > 2. Number B

### CT-75 — task list inside nested blockquote (depth 2)

> Outer quote
>
> > Container quote line
> >
> > - [ ] Task A
> > - [x] Task B

### CT-76 — code block inside nested blockquote (depth 2)

> Outer quote
>
> > Container quote line
> >
> > ```
> > code line
> > ```

### CT-77 — blockquote inside nested blockquote (depth 2)

> Outer quote
>
> > Container quote line
> >
> > > Quoted line

### CT-78 — table inside nested blockquote (depth 2)

> Outer quote
>
> > Container quote line
> >
> > | K | V |
> > |---|---|
> > | k1 | v1 |

### CT-79 — image inside nested blockquote (depth 2)

> Outer quote
>
> > Container quote line
> >
> > ![pixel](https://www.gstatic.com/images/branding/product/2x/docs_48dp.png)

### CT-80 — rule inside nested blockquote (depth 2)

> Outer quote
>
> > Container quote line
> >
> > ***
