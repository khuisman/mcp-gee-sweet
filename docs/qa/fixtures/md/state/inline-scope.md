### IS-01 — nested and stray sub/sup

<sup>a<sub>b</sub>c</sup>d and <sup>e</sub>f</sup>g; <sup>h<sub>i</sup>j</sub>k.

### IS-02 — strike inside strike

<s>h<del>i</del>j</s>k.

### IS-03 — unclosed tags end with their paragraph

<mark><del><sup>unclosed

The paragraph after them is plain.

### IS-04 — table cells

| one | two |
|---|---|
| <sup>x</sup> ~~y~~ <mark>z</mark> | <mark>open |
| plain | plain |

### IS-06 — a carried tag closes in the next paragraph

<b>one

two</b> three

four

### IS-05 — unclosed s carries on (keep this case last)

<s>struck

This paragraph is struck too.
