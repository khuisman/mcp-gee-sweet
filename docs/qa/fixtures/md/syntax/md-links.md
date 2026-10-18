### LK-01 — inline link

See [the docs](https://example.com/docs).

### LK-02 — inline link with a title

See [the titled docs](https://example.com/titled "Docs title").

### LK-03 — reference-style links

See [full reference][ref-a], [collapsed][] and [shortcut].

[ref-a]: https://example.com/ref-a
[collapsed]: https://example.com/collapsed
[shortcut]: https://example.com/shortcut

### LK-04 — angle-bracket autolink

Visit <https://example.com/angle>.

### LK-05 — bare URL (extended autolink)

Visit https://example.com/bare for details. Trailing period is not part of it: https://example.com/end.

### LK-06 — www autolink

Visit www.example.com/www for details.

### LK-07 — email autolinks

Write to <team@example.com> or team@example.com.

### LK-08 — link inside bold and bold inside link

**[Bold link](https://example.com/b1)** and [**link with bold**](https://example.com/b2).

### LK-09 — link-looking text inside code is not a link

`[not a link](https://example.com/c)` and `https://example.com/in-code`.

### LK-10 — link inside a heading

#### Heading with a [link](https://example.com/h)

### LK-11 — URL with query string and parentheses

[Query link](https://example.com/search?q=a&b=c) and [paren link](https://en.wikipedia.org/wiki/Example_(disambiguation)).

### LK-12 — relative link

See [the guide](./guide.md) and [an anchor](#lk-01).
