# Inline formatting matrix

### IN-01 — italic inside bold

Before **outer *inner* outer** after.

### IN-02 — strike inside bold

Before **outer ~~inner~~ outer** after.

### IN-03 — code inside bold

Before **outer `inner` outer** after.

### IN-04 — link inside bold

Before **outer [inner](https://example.com/inline) outer** after.

### IN-05 — bold inside italic

Before *outer **inner** outer* after.

### IN-06 — strike inside italic

Before *outer ~~inner~~ outer* after.

### IN-07 — code inside italic

Before *outer `inner` outer* after.

### IN-08 — link inside italic

Before *outer [inner](https://example.com/inline) outer* after.

### IN-09 — bold inside strike

Before ~~outer **inner** outer~~ after.

### IN-10 — italic inside strike

Before ~~outer *inner* outer~~ after.

### IN-11 — code inside strike

Before ~~outer `inner` outer~~ after.

### IN-12 — link inside strike

Before ~~outer [inner](https://example.com/inline) outer~~ after.

### IN-13 — bold inside code

Before `**inner** in code` after.

### IN-14 — italic inside code

Before `*inner* in code` after.

### IN-15 — strike inside code

Before `~~inner~~ in code` after.

### IN-16 — link inside code

Before `[inner](https://example.com/inline) in code` after.

### IN-17 — bold inside link

Before [outer **inner** outer](https://example.com/inline) after.

### IN-18 — italic inside link

Before [outer *inner* outer](https://example.com/inline) after.

### IN-19 — strike inside link

Before [outer ~~inner~~ outer](https://example.com/inline) after.

### IN-20 — code inside link

Before [outer `inner` outer](https://example.com/inline) after.

### IN-21 — every inline style inside a paragraph

**B** *I* ~~S~~ `C` [L](https://example.com/inline)

### IN-22 — every inline style inside a heading 2

## Heading **B** *I* ~~S~~ `C` [L](https://example.com/inline)

### IN-23 — every inline style inside a heading 6

###### Heading **B** *I* ~~S~~ `C` [L](https://example.com/inline)

### IN-24 — every inline style inside a bullet item, level 0

- Item **B** *I* ~~S~~ `C` [L](https://example.com/inline)

### IN-25 — every inline style inside a bullet item, level 2

- Top
    - Mid
        - Item **B** *I* ~~S~~ `C` [L](https://example.com/inline)

### IN-26 — every inline style inside a numbered item, level 0

1. Item **B** *I* ~~S~~ `C` [L](https://example.com/inline)

### IN-27 — every inline style inside a numbered item, level 2

1. Top
    1. Mid
        1. Item **B** *I* ~~S~~ `C` [L](https://example.com/inline)

### IN-28 — every inline style inside a task item

- [ ] Task **B** *I* ~~S~~ `C` [L](https://example.com/inline)

### IN-29 — every inline style inside a table header cell

| Head **B** *I* ~~S~~ `C` [L](https://example.com/inline) | H2 |
|---|---|
| a | b |

### IN-30 — every inline style inside a table body cell

| H1 | H2 |
|---|---|
| Cell **B** *I* ~~S~~ `C` [L](https://example.com/inline) | b |

### IN-31 — every inline style inside a blockquote

> Quote **B** *I* ~~S~~ `C` [L](https://example.com/inline)

### IN-32 — every inline style inside a nested blockquote

> Outer
>
> > Quote **B** *I* ~~S~~ `C` [L](https://example.com/inline)
