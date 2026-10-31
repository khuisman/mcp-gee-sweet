### IM-01 — public URL image on its own line

![Placeholder from a URL](https://www.gstatic.com/images/branding/product/2x/docs_48dp.png)

### IM-02 — image inline in a paragraph

Text before ![inline icon](https://www.gstatic.com/images/branding/product/2x/docs_48dp.png) text after.

### IM-03 — reference-style image

![Reference image][img-ref]

[img-ref]: https://www.gstatic.com/images/branding/product/2x/docs_48dp.png

### IM-04 — local path image (absolute; substituted at run time)

![Local pixel]({QA_IMAGE_LOCAL_PATH})

### IM-05 — local path image relative to this .md file

![Relative pixel](../../qa-fixture-pixel.png)

### IM-06 — drive: image (substituted at run time)

![Drive pixel](drive:{QA_IMAGE_DRIVE_ID})

### IM-07 — linked image

[![Linked image](https://www.gstatic.com/images/branding/product/2x/docs_48dp.png)](https://example.com/linked-image)

### IM-08 — image with an empty alt

![](https://www.gstatic.com/images/branding/product/2x/docs_48dp.png)

### IM-09 — image in a list item and in a table cell

- Bullet with an image ![icon](https://www.gstatic.com/images/branding/product/2x/docs_48dp.png)

| Name | Icon |
|------|------|
| Docs | ![icon](https://www.gstatic.com/images/branding/product/2x/docs_48dp.png) |

### IM-10 — local path with a space and a non-ASCII character

![Spaced accented pixel](../../qa fixture pixel é.png)

### IM-11 — linked image Docs can't embed (SVG)

[![Build status](https://img.shields.io/badge/build-passing-brightgreen)](https://example.com/ci)

### IM-12 — image Docs can't embed, empty alt

Before ![](https://img.shields.io/badge/coverage-90%25-green) after.

### IM-13 — image Docs can't embed, in a heading

[Go to Badge heading](#badge-heading)

#### Badge heading ![build](https://img.shields.io/badge/build-passing-brightgreen)
